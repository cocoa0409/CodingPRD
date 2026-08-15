"""Request-shape validation helpers (validation rung 3.4).

All field-level failures raise ERR_INVALID_REQUEST except the pinned
window/range sanity errors (ERR_INVALID_WINDOW, ERR_INVALID_TEMP_RANGE), which
callers raise explicitly.
"""
from flask import request

from errors import raise_error, ERR_INVALID_REQUEST
from util import parse_dt

MISSING = object()


def get_body() -> dict:
    """Parse the JSON request body. Absent body -> {}; malformed JSON or a
    non-object document -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise_error(ERR_INVALID_REQUEST, "request body is not valid JSON")
    if not isinstance(data, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def req_str(body: dict, key: str, min_len: int = 1) -> str:
    v = body.get(key, MISSING)
    if v is MISSING:
        raise_error(ERR_INVALID_REQUEST, f"missing required field: {key}")
    if not isinstance(v, str) or len(v) < min_len:
        raise_error(ERR_INVALID_REQUEST, f"field {key} must be a string of at least {min_len} character(s)")
    return v


def opt_str(body: dict, key: str, min_len: int = 1):
    v = body.get(key, MISSING)
    if v is MISSING or v is None:
        return None
    if not isinstance(v, str) or len(v) < min_len:
        raise_error(ERR_INVALID_REQUEST, f"field {key} must be a string of at least {min_len} character(s)")
    return v


def req_int(body: dict, key: str, min_val=None) -> int:
    v = body.get(key, MISSING)
    if v is MISSING:
        raise_error(ERR_INVALID_REQUEST, f"missing required field: {key}")
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"field {key} must be an integer")
    if min_val is not None and v < min_val:
        raise_error(ERR_INVALID_REQUEST, f"field {key} must be >= {min_val}")
    return v


def opt_int(body: dict, key: str, min_val=None):
    v = body.get(key, MISSING)
    if v is MISSING or v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"field {key} must be an integer")
    if min_val is not None and v < min_val:
        raise_error(ERR_INVALID_REQUEST, f"field {key} must be >= {min_val}")
    return v


def req_num(body: dict, key: str):
    v = body.get(key, MISSING)
    if v is MISSING:
        raise_error(ERR_INVALID_REQUEST, f"missing required field: {key}")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"field {key} must be a number")
    return v


def opt_num(body: dict, key: str):
    v = body.get(key, MISSING)
    if v is MISSING or v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"field {key} must be a number")
    return v


def req_enum(body: dict, key: str, allowed) -> str:
    v = body.get(key, MISSING)
    if v is MISSING:
        raise_error(ERR_INVALID_REQUEST, f"missing required field: {key}")
    if not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"field {key} must be one of {sorted(allowed)}")
    return v


def req_dt(body: dict, key: str):
    v = body.get(key, MISSING)
    if v is MISSING:
        raise_error(ERR_INVALID_REQUEST, f"missing required field: {key}")
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"field {key} must be an ISO 8601 datetime string")


def req_str_list(body: dict, key: str, min_items: int = 1) -> list:
    v = body.get(key, MISSING)
    if v is MISSING:
        raise_error(ERR_INVALID_REQUEST, f"missing required field: {key}")
    if not isinstance(v, list) or len(v) < min_items:
        raise_error(ERR_INVALID_REQUEST, f"field {key} must be an array of at least {min_items} item(s)")
    for item in v:
        if not isinstance(item, str) or not item:
            raise_error(ERR_INVALID_REQUEST, f"field {key} must contain non-empty strings")
    return v


def pagination_params():
    """limit (default 10, 1..100) and offset (default 0, >= 0) from the query string."""
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items: list):
    """Apply pagination params to an already-sorted list; returns (page, total, limit, offset)."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return page, total, limit, offset
