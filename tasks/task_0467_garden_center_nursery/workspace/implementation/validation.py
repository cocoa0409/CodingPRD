"""Field-shape validators (priority 5, ERR_INVALID_REQUEST 422)."""
import errors
from errors import err


def _bad(msg):
    err(errors.ERR_INVALID_REQUEST, msg)


def req_str(data, key):
    v = data.get(key)
    if not isinstance(v, str) or v == "":
        _bad(f"{key} is required and must be a non-empty string")
    return v


def opt_str(data, key, default=""):
    if key not in data or data.get(key) is None:
        return default
    v = data.get(key)
    if not isinstance(v, str):
        _bad(f"{key} must be a string")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(data, key):
    v = data.get(key)
    if not _is_int(v):
        _bad(f"{key} is required and must be an integer")
    return v


def opt_int(data, key, default):
    if key not in data or data.get(key) is None:
        return default
    v = data.get(key)
    if not _is_int(v):
        _bad(f"{key} must be an integer")
    return v


def req_int_in_range(data, key, lo, hi):
    v = req_int(data, key)
    if v < lo or v > hi:
        _bad(f"{key} must be in {lo}..{hi}")
    return v


def opt_int_in_range(data, key, default, lo, hi):
    v = opt_int(data, key, default)
    if v < lo or v > hi:
        _bad(f"{key} must be in {lo}..{hi}")
    return v


def req_int_min(data, key, minimum):
    v = req_int(data, key)
    if v < minimum:
        _bad(f"{key} must be >= {minimum}")
    return v


def req_int_gt(data, key, threshold):
    v = req_int(data, key)
    if v <= threshold:
        _bad(f"{key} must be > {threshold}")
    return v


def req_enum(data, key, allowed):
    v = data.get(key)
    if not isinstance(v, str) or v not in allowed:
        _bad(f"{key} must be one of {sorted(allowed)}")
    return v


def opt_enum(data, key, allowed, default):
    if key not in data or data.get(key) is None:
        return default
    v = data.get(key)
    if not isinstance(v, str) or v not in allowed:
        _bad(f"{key} must be one of {sorted(allowed)}")
    return v


def opt_bool(data, key, default=False):
    if key not in data or data.get(key) is None:
        return default
    v = data.get(key)
    if not isinstance(v, bool):
        _bad(f"{key} must be a boolean")
    return v


def req_datetime(data, key):
    from clock import parse_iso8601
    v = data.get(key)
    if not isinstance(v, str) or not v.strip():
        _bad(f"{key} is required and must be an ISO-8601 datetime")
    try:
        return parse_iso8601(v)
    except (ValueError, TypeError):
        _bad(f"{key} must be a valid ISO-8601 datetime")
