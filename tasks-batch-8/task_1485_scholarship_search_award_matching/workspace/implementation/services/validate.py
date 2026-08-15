"""Request-shape validation helpers (PRD §2.8 step 6)."""

import clock
from errors import raise_err


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise_err("ERR_VALIDATION", "Missing required field: %s" % f)


def req_string(data, f):
    v = data.get(f)
    if not isinstance(v, str) or v == "":
        raise_err("ERR_VALIDATION", "Field %s must be a non-empty string" % f)
    return v


def req_int(data, f, lo=None, hi=None):
    v = data.get(f)
    if not is_int(v):
        raise_err("ERR_VALIDATION", "Field %s must be an integer" % f)
    if lo is not None and v < lo:
        raise_err("ERR_VALIDATION", "Field %s below minimum" % f)
    if hi is not None and v > hi:
        raise_err("ERR_VALIDATION", "Field %s above maximum" % f)
    return v


def req_enum(data, f, allowed):
    v = data.get(f)
    if v not in allowed:
        raise_err("ERR_VALIDATION", "Field %s must be one of %s" % (f, sorted(allowed)))
    return v


def opt_int(data, f, lo=None, hi=None, default=None, allow_null=True):
    if f not in data:
        return default
    v = data[f]
    if v is None and allow_null:
        return None
    if not is_int(v):
        raise_err("ERR_VALIDATION", "Field %s must be an integer" % f)
    if lo is not None and v < lo:
        raise_err("ERR_VALIDATION", "Field %s below minimum" % f)
    if hi is not None and v > hi:
        raise_err("ERR_VALIDATION", "Field %s above maximum" % f)
    return v


def opt_bool(data, f, default=False):
    if f not in data or data[f] is None:
        return default
    v = data[f]
    if not isinstance(v, bool):
        raise_err("ERR_VALIDATION", "Field %s must be a boolean" % f)
    return v


def opt_list(data, f, default=None):
    if f not in data or data[f] is None:
        return list(default) if default is not None else None
    v = data[f]
    if not isinstance(v, list):
        raise_err("ERR_VALIDATION", "Field %s must be an array" % f)
    return list(v)


def req_iso_datetime(data, f):
    v = data.get(f)
    if not isinstance(v, str):
        raise_err("ERR_VALIDATION", "Field %s must be an ISO8601 datetime string" % f)
    try:
        clock.parse_iso(v)
    except ValueError:
        raise_err("ERR_VALIDATION", "Field %s is not a valid ISO8601 datetime" % f)
    return v


def req_date(data, f):
    v = data.get(f)
    if not isinstance(v, str):
        raise_err("ERR_VALIDATION", "Field %s must be a YYYY-MM-DD date string" % f)
    try:
        clock.parse_date(v)
    except ValueError:
        raise_err("ERR_VALIDATION", "Field %s is not a valid YYYY-MM-DD date" % f)
    return v
