"""Request body / query validation helpers and pagination parsing."""
from flask import request

from errors import ApiError, ERR_INVALID_REQUEST
from timeutil import parse_iso


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Malformed JSON payload", 400)
    return data


def _present(data, name):
    if name not in data or data[name] is None:
        raise ApiError(ERR_INVALID_REQUEST, "Required field missing: %s" % name, 400)
    return data[name]


def req_str(data, name):
    v = _present(data, name)
    if not isinstance(v, str) or not v.strip():
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % name, 400)
    return v


def opt_str(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a string" % name, 400)
    return v


def req_int(data, name):
    v = _present(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be an integer" % name, 400)
    return v


def req_bool(data, name):
    v = _present(data, name)
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a boolean" % name, 400)
    return v


def opt_bool(data, name, default=False):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a boolean" % name, 400)
    return v


def req_number(data, name):
    v = _present(data, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a number" % name, 400)
    return v


def req_enum(data, name, allowed):
    v = _present(data, name)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field %s must be one of %s" % (name, ", ".join(allowed)),
            400,
        )
    return v


def req_dt(data, name):
    v = _present(data, name)
    try:
        return parse_iso(v)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be an ISO8601 datetime" % name, 400)


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (insertion order breaks same-instant ties),
    then apply offset/limit. Returns (page, total_count)."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    return ordered[offset:offset + limit], total
