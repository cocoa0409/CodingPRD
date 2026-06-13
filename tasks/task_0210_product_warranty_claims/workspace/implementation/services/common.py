"""Shared route helpers: body parsing, pagination, field validation."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from flask import request

from errors import APIError, ERR_INVALID_REQUEST

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_json_body() -> Dict[str, Any]:
    """Return the parsed JSON object body, or {} for an empty body.

    A present-but-non-object or malformed JSON body -> ERR_INVALID_REQUEST.
    """
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400, "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise APIError(ERR_INVALID_REQUEST, 400, "Body must be a JSON object")
    return data


def parse_pagination() -> tuple:
    """Parse limit/offset query params with defaults/min/max (PRD §2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT:
            limit = PAGINATION_MIN_LIMIT
        elif limit > PAGINATION_MAX_LIMIT:
            limit = PAGINATION_MAX_LIMIT
    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(rows: List[Dict[str, Any]], limit: int, offset: int) -> tuple:
    """Sort by created_at (insertion seq) ASC, then window. Returns (page, total)."""
    rows = sorted(rows, key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total


# ---- field validation -------------------------------------------------------

def require_fields(body: Dict[str, Any], names: List[str]) -> None:
    for n in names:
        if n not in body or body[n] is None:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {n}")


def require_str(body: Dict[str, Any], name: str, *, allow_empty: bool = False) -> str:
    v = body.get(name)
    if not isinstance(v, str):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be a string")
    if not allow_empty and v.strip() == "":
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be non-empty")
    return v


def require_enum(body: Dict[str, Any], name: str, allowed: set) -> str:
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be one of {sorted(allowed)}")
    return v


def require_int(body: Dict[str, Any], name: str, *, minimum: Optional[int] = None) -> int:
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be >= {minimum}")
    return v


def require_bool(body: Dict[str, Any], name: str, default: Optional[bool] = None) -> Optional[bool]:
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be a boolean")
    return v
