"""Request body parsing / structural validation helpers.

Raise ERR_INVALID_REQUEST for structural problems (missing required fields,
bad types, bad enums, quantity<1, unknown option ids).
"""
from flask import request

from errors import err
from timeutil import parse_iso

_MISSING = object()


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, key):
    v = body.get(key, _MISSING)
    if v is _MISSING or not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"Field '{key}' is required and must be a non-empty string")
    return v


def opt_str(body, key, default=None):
    v = body.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field '{key}' must be a string")
    return v


def req_int(body, key):
    v = body.get(key, _MISSING)
    if v is _MISSING or not _is_int(v):
        raise err("ERR_INVALID_REQUEST", f"Field '{key}' is required and must be an integer")
    return v


def opt_int(body, key, default):
    v = body.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    if not _is_int(v):
        raise err("ERR_INVALID_REQUEST", f"Field '{key}' must be an integer")
    return v


def req_number(body, key):
    v = body.get(key, _MISSING)
    if v is _MISSING or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field '{key}' is required and must be a number")
    return v


def req_bool_default(body, key, default):
    v = body.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field '{key}' must be a boolean")
    return v


def req_enum(body, key, allowed):
    v = req_str(body, key)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field '{key}' must be one of {sorted(allowed)}")
    return v


def opt_enum(body, key, allowed, default=None):
    v = opt_str(body, key, None)
    if v is None:
        return default
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field '{key}' must be one of {sorted(allowed)}")
    return v


def req_datetime(body, key):
    v = body.get(key, _MISSING)
    if v is _MISSING or v is None:
        raise err("ERR_INVALID_REQUEST", f"Field '{key}' is required")
    dt = parse_iso(v)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", f"Field '{key}' must be an ISO 8601 datetime")
    return dt


def parse_pagination():
    """limit default 10 (clamped [1,100]); offset default 0 (clamped >=0)."""
    args = request.args
    raw_limit = args.get("limit")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    raw_offset = args.get("offset")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def req_str_list(body, key, default=None):
    v = body.get(key, _MISSING)
    if v is _MISSING or v is None:
        return list(default) if default is not None else []
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise err("ERR_INVALID_REQUEST", f"Field '{key}' must be an array of strings")
    return v
