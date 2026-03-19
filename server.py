import os
import time
import base64
import json
import requests
from typing import Any, Dict, List

from fastmcp import FastMCP
from fastapi import FastAPI
import uvicorn

mcp = FastMCP("snippet-library")

GITHUB_OWNER = os.environ["GITHUB_OWNER"]
GITHUB_REPO = os.environ["GITHUB_REPO"]
GITHUB_PATH = os.environ.get(
    "GITHUB_PATH",
    "snippets/digital_process_governance_snippet_library.json"
)
GITHUB_REF = os.environ.get("GITHUB_REF", "main")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "300"))

_cache_data = None
_cache_loaded_at = 0.0


def github_headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def fetch_json_from_github() -> Dict[str, Any]:
    global _cache_data, _cache_loaded_at

    now = time.time()
    if _cache_data is not None and (now - _cache_loaded_at) < CACHE_TTL_SECONDS:
        return _cache_data

    url = (
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/"
        f"{GITHUB_PATH}?ref={GITHUB_REF}"
    )

    resp = requests.get(url, headers=github_headers(), timeout=20)
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("encoding") != "base64":
        raise RuntimeError("Expected base64 content from GitHub")

    raw_bytes = base64.b64decode(payload["content"])
    data = json.loads(raw_bytes.decode("utf-8"))

    _cache_data = data
    _cache_loaded_at = now
    return data


def get_by_path(data: Dict[str, Any], path: str) -> Dict[str, Any]:
    current: Any = data
    parts = [p for p in path.split(".") if p]

    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return {
                "found": False,
                "path": path,
                "value": None,
            }

    return {
        "found": True,
        "path": path,
        "value": current,
    }


def flatten_paths(obj: Any, prefix: str = "") -> List[str]:
    paths: List[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            next_prefix = f"{prefix}.{key}" if prefix else key
            paths.append(next_prefix)
            paths.extend(flatten_paths(value, next_prefix))
    return paths


@mcp.tool
def list_domains() -> Dict[str, Any]:
    """Return the available domains from the snippet library."""
    data = fetch_json_from_github()
    playbooks = data.get("playbooks", {})
    domains = sorted(playbooks.keys()) if isinstance(playbooks, dict) else []
    return {"domains": domains}


@mcp.tool
def get_value_by_path(path: str) -> Dict[str, Any]:
    """Return an exact value from the snippet library by dot path."""
    data = fetch_json_from_github()
    return get_by_path(data, path)


@mcp.tool
def get_domain_bundle(domain: str) -> Dict[str, Any]:
    """Return the playbook and question bundles for a given domain."""
    data = fetch_json_from_github()

    return {
        "domain": domain,
        "playbook": data.get("playbooks", {}).get(domain),
        "clarify_questions": data.get("question_library", {}).get("clarify", {}).get(domain, []),
        "challenge_questions": data.get("question_library", {}).get("challenge", {}).get(domain, []),
        "validate_questions": data.get("question_library", {}).get("validate", {}).get(domain, []),
    }


@mcp.tool
def list_paths_for_domain(domain: str) -> Dict[str, Any]:
    """Return all exact paths relevant to a given domain."""
    data = fetch_json_from_github()

    subtree = {
        "playbooks": {domain: data.get("playbooks", {}).get(domain)},
        "question_library": {
            "clarify": {domain: data.get("question_library", {}).get("clarify", {}).get(domain, [])},
            "challenge": {domain: data.get("question_library", {}).get("challenge", {}).get(domain, [])},
            "validate": {domain: data.get("question_library", {}).get("validate", {}).get(domain, [])},
        },
    }

    return {"domain": domain, "paths": flatten_paths(subtree)}


app = FastAPI()
app.mount("/mcp", mcp.http_app())


@app.get("/")
def healthcheck():
    return {"status": "ok", "message": "Snippet MCP server is running"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)