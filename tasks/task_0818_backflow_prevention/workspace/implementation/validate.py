"""Request-body field validation (ERR_VALIDATION / ERR_INVALID_TIME_RANGE)."""

from flask import request

from util import ApiError, parse_dt

_MISSING = object()


def _fail(msg):
    raise ApiError("ERR_VALIDATION", 400, msg)


def json_object():
    """Return the JSON request body as a dict, or raise ERR_VALIDATION."""
    body = request.get_json(silent=True)
    if body is None:
        _fail("request body must be a JSON object")
    if not isinstance(body, dict):
        _fail("request body must be a JSON object")
    return body


def optional_json_object():
    """Body for action endpoints that may omit it; returns {} when absent."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        _fail("request body must be a JSON object")
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_nonempty_str(d, key):
    v = d.get(key, _MISSING)
    if v is _MISSING or v is None:
        _fail(f"{key} is required")
    if not isinstance(v, str) or v.strip() == "":
        _fail(f"{key} must be a non-empty string")
    return v


def req_str(d, key):
    v = d.get(key, _MISSING)
    if v is _MISSING or v is None:
        _fail(f"{key} is required")
    if not isinstance(v, str):
        _fail(f"{key} must be a string")
    return v


def opt_str(d, key):
    v = d.get(key, _MISSING)
    if v is _MISSING or v is None:
        return None
    if not isinstance(v, str):
        _fail(f"{key} must be a string")
    return v


def req_enum(d, key, allowed):
    v = d.get(key, _MISSING)
    if v is _MISSING or v is None:
        _fail(f"{key} is required")
    if not isinstance(v, str) or v not in allowed:
        _fail(f"{key} must be one of {sorted(allowed)}")
    return v


def opt_enum(d, key, allowed):
    v = d.get(key, _MISSING)
    if v is _MISSING or v is None:
        return None
    if not isinstance(v, str) or v not in allowed:
        _fail(f"{key} must be one of {sorted(allowed)}")
    return v


def req_int(d, key, lo=None, hi=None):
    v = d.get(key, _MISSING)
    if v is _MISSING or v is None:
        _fail(f"{key} is required")
    if not _is_int(v):
        _fail(f"{key} must be an integer")
    if lo is not None and v < lo:
        _fail(f"{key} must be >= {lo}")
    if hi is not None and v > hi:
        _fail(f"{key} must be <= {hi}")
    return v


def opt_int(d, key, lo=None, hi=None, default=None):
    v = d.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    if not _is_int(v):
        _fail(f"{key} must be an integer")
    if lo is not None and v < lo:
        _fail(f"{key} must be >= {lo}")
    if hi is not None and v > hi:
        _fail(f"{key} must be <= {hi}")
    return v


def req_number(d, key, minimum=None):
    v = d.get(key, _MISSING)
    if v is _MISSING or v is None:
        _fail(f"{key} is required")
    if not _is_num(v):
        _fail(f"{key} must be a number")
    if minimum is not None and v < minimum:
        _fail(f"{key} must be >= {minimum}")
    return v


def opt_number(d, key, minimum=None):
    v = d.get(key, _MISSING)
    if v is _MISSING or v is None:
        return None
    if not _is_num(v):
        _fail(f"{key} must be a number")
    if minimum is not None and v < minimum:
        _fail(f"{key} must be >= {minimum}")
    return v


def req_datetime(d, key):
    v = d.get(key, _MISSING)
    if v is _MISSING or v is None:
        _fail(f"{key} is required")
    if not isinstance(v, str):
        _fail(f"{key} must be an ISO-8601 string")
    try:
        return parse_dt(v)
    except ValueError:
        _fail(f"{key} must be a valid ISO-8601 datetime")
