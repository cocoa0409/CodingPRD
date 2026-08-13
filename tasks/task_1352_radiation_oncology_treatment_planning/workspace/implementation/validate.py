"""Request-schema field validators (validation priority 4 -> ERR_INVALID_REQUEST)."""
from errors import err, ERR_INVALID_REQUEST
from timeutil import parse_datetime, parse_date


def req_str(body, field, allow_empty=False):
    v = body.get(field)
    if not isinstance(v, str) or (not allow_empty and not v.strip()):
        err(ERR_INVALID_REQUEST, f"{field} is required and must be a non-empty string")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        err(ERR_INVALID_REQUEST, f"{field} must be a string")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, field, minimum=None):
    v = body.get(field)
    if not _is_int(v):
        err(ERR_INVALID_REQUEST, f"{field} is required and must be an integer")
    if minimum is not None and v < minimum:
        err(ERR_INVALID_REQUEST, f"{field} must be >= {minimum}")
    return v


def req_num(body, field, minimum_exclusive=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err(ERR_INVALID_REQUEST, f"{field} is required and must be a number")
    if minimum_exclusive is not None and not (v > minimum_exclusive):
        err(ERR_INVALID_REQUEST, f"{field} must be > {minimum_exclusive}")
    return v


def req_enum(body, field, values):
    v = body.get(field)
    if not isinstance(v, str) or v not in values:
        err(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(values)}")
    return v


def opt_enum(body, field, values, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v not in values:
        err(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(values)}")
    return v


def opt_bool(body, field, default=False):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        err(ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return v


def req_dt_pair(body):
    """Validate start_time / end_time: both parse, end strictly after start."""
    s_raw = body.get("start_time")
    e_raw = body.get("end_time")
    s = parse_datetime(s_raw)
    t = parse_datetime(e_raw)
    if s is None:
        err(ERR_INVALID_REQUEST, "start_time must be a valid ISO 8601 datetime")
    if t is None:
        err(ERR_INVALID_REQUEST, "end_time must be a valid ISO 8601 datetime")
    if not (t > s):
        err(ERR_INVALID_REQUEST, "end_time must be strictly after start_time")
    return s_raw, e_raw, s, t


def req_date(body, field):
    v = body.get(field)
    d = parse_date(v)
    if d is None:
        err(ERR_INVALID_REQUEST, f"{field} must be a valid ISO 8601 date (YYYY-MM-DD)")
    return v, d


def req_str_list(body, field, min_len=0, allow_missing=False):
    v = body.get(field)
    if v is None and allow_missing:
        return []
    if not isinstance(v, list) or len(v) < min_len:
        err(ERR_INVALID_REQUEST, f"{field} must be an array of at least {min_len} string(s)")
    for item in v:
        if not isinstance(item, str) or not item.strip():
            err(ERR_INVALID_REQUEST, f"{field} entries must be non-empty strings")
    return v
