"""Common helpers: body parsing, pagination params, OCC version checks."""
from typing import Any, Optional, Tuple

from flask import request

from .errors import APIError


def get_json_body() -> dict:
    """Returns the request JSON body (empty dict if missing)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise APIError("ERR_VALIDATION", "Request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def get_pagination_params() -> Tuple[int, int]:
    """Parse limit/offset from query string per PRD §2.3.

    Defaults: limit=10, offset=0. Bounds: limit in [1,100]; offset >= 0.
    Violations raise ERR_PAGINATION_PARAMS (HTTP 422).
    """
    args = request.args
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise APIError("ERR_PAGINATION_PARAMS", "limit and offset must be integers")
    if limit < 1 or limit > 100:
        raise APIError("ERR_PAGINATION_PARAMS", "limit must be in [1, 100]")
    if offset < 0:
        raise APIError("ERR_PAGINATION_PARAMS", "offset must be >= 0")
    return limit, offset


def check_version(record: dict, payload_version: Any) -> None:
    """Optimistic concurrency check (PRD §2.6).

    When the client omits version, no check is performed; otherwise the stored
    version must equal payload_version exactly.
    """
    if payload_version is None:
        return
    if not isinstance(payload_version, int) or isinstance(payload_version, bool):
        raise APIError("ERR_VALIDATION", "version must be an integer")
    if record.get("version") != payload_version:
        raise APIError("ERR_VERSION_CONFLICT", "Submitted version does not match current version")


def require_field(body: dict, name: str) -> Any:
    if name not in body or body[name] is None:
        raise APIError("ERR_VALIDATION", f"Field '{name}' is required")
    return body[name]


def optional_field(body: dict, name: str, default: Optional[Any] = None) -> Any:
    if name not in body:
        return default
    return body[name]


def paginate(items: list, limit: int, offset: int) -> Tuple[list, int]:
    total = len(items)
    return items[offset:offset + limit], total
