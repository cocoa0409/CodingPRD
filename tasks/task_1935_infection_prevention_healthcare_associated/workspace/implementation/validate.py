"""Payload validation helpers (priority 3 — schema, ERR_INVALID_REQUEST)."""
from datetime import datetime

from errors import raise_err
from util import parse_dt


def body():
    from flask import request
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        raise_err(ERR_INVALID_REQUEST_PAIR, "Request body must be a JSON object")
    return b


ERR_INVALID_REQUEST_PAIR = ("ERR_INVALID_REQUEST", 400)


def require_fields(b, fields):
    for f in fields:
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST_PAIR, f"Missing required field: {f}")


def req_string(b, f, min_len=1):
    v = b.get(f)
    if not isinstance(v, str) or len(v) < min_len:
        raise_err(ERR_INVALID_REQUEST_PAIR, f"Field {f} must be a string of at least {min_len} chars")
    return v


def opt_string(b, f, min_len=0):
    v = b.get(f)
    if v is None:
        return None
    if not isinstance(v, str) or len(v) < min_len:
        raise_err(ERR_INVALID_REQUEST_PAIR, f"Field {f} must be a string of at least {min_len} chars")
    return v


def req_enum(b, f, allowed):
    v = b.get(f)
    if v not in allowed:
        raise_err(ERR_INVALID_REQUEST_PAIR, f"Field {f} must be one of {sorted(allowed)}")
    return v


def req_int(b, f, min_v=None, max_v=None):
    v = b.get(f)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST_PAIR, f"Field {f} must be an integer")
    if min_v is not None and v < min_v:
        raise_err(ERR_INVALID_REQUEST_PAIR, f"Field {f} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise_err(ERR_INVALID_REQUEST_PAIR, f"Field {f} must be <= {max_v}")
    return v


def opt_int(b, f, min_v=None, max_v=None):
    if f not in b or b[f] is None:
        return None
    return req_int(b, f, min_v, max_v)


def req_number(b, f):
    v = b.get(f)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_INVALID_REQUEST_PAIR, f"Field {f} must be a number")
    return v


def opt_number(b, f):
    if f not in b or b[f] is None:
        return None
    return req_number(b, f)


def req_bool(b, f):
    v = b.get(f)
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST_PAIR, f"Field {f} must be a boolean")
    return v


def opt_bool(b, f, default=None):
    if f not in b or b[f] is None:
        return default
    return req_bool(b, f)


def req_dt(b, f):
    v = b.get(f)
    if v is None:
        raise_err(ERR_INVALID_REQUEST_PAIR, f"Missing required field: {f}")
    try:
        return parse_dt(v, f)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST_PAIR, f"Field {f} must be an ISO-8601 timestamp")


def opt_dt(b, f):
    if f not in b or b[f] is None:
        return None
    try:
        return parse_dt(b[f], f)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST_PAIR, f"Field {f} must be an ISO-8601 timestamp")


def req_month(b, f):
    v = b.get(f)
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST_PAIR, f"Field {f} must be 'YYYY-MM'")
    parts = v.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        raise_err(ERR_INVALID_REQUEST_PAIR, f"Field {f} must be 'YYYY-MM'")
    try:
        y = int(parts[0])
        m = int(parts[1])
        if not (1 <= m <= 12):
            raise ValueError
        datetime(y, m, 1)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST_PAIR, f"Field {f} must be a valid 'YYYY-MM' month")
    return v


def pagination_args():
    """limit/offset per scaffold response_envelope.pagination_defaults: limit 10 (1..100), offset 0."""
    from flask import request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST_PAIR, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST_PAIR, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST_PAIR, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST_PAIR, "offset must be >= 0")
    return limit, offset
