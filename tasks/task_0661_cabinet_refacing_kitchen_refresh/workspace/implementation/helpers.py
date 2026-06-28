"""Shared request helpers: body parsing, pagination, field validation."""
from flask import request

from errors import err

MISSING = object()


def get_json_body():
    """Return the parsed JSON body as a dict (empty dict when no body)."""
    if request.method in ("GET", "DELETE"):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3).

    limit default 10, min 1, max 100; offset default 0. Out-of-range values
    are rejected as ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit out of range")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (tie-broken by _seq) and slice."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def require_fields(body, fields):
    for f in fields:
        if body.get(f, MISSING) is MISSING:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_str(body, field, allow_empty=False):
    require_fields(body, [field])
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a string")
    if not allow_empty and v == "":
        raise err("ERR_INVALID_REQUEST", f"{field} must be non-empty")
    return v


def require_int(body, field, minimum=None):
    require_fields(body, [field])
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"{field} must be >= {minimum}")
    return v


def require_number(body, field):
    require_fields(body, [field])
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a number")
    return v


def require_enum(body, field, allowed):
    v = require_str(body, field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(allowed)}")
    return v


def optional_bool(body, field, default=None):
    if body.get(field, MISSING) is MISSING:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a boolean")
    return v


def optional_number(body, field, default=None):
    if body.get(field, MISSING) is MISSING:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a number")
    return v


def optional_int(body, field, default=None):
    if body.get(field, MISSING) is MISSING:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an integer")
    return v
