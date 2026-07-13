"""Body-shape and query-parameter validation (validation priority 4)."""
from flask import request

from errors import ApiError

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def bad():
    raise ApiError("ERR_INVALID_REQUEST")


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        bad()
    return data


def req_str(data, key, min_len=1, max_len=None):
    v = data.get(key)
    if not isinstance(v, str):
        bad()
    if len(v) < min_len:
        bad()
    if max_len is not None and len(v) > max_len:
        bad()
    return v


def opt_str(data, key, default=None, min_len=0, max_len=None):
    if key not in data or data[key] is None:
        return default
    return req_str(data, key, min_len, max_len)


def req_email(data, key):
    v = req_str(data, key, 1, None)
    if "@" not in v:
        bad()
    return v


def req_enum(data, key, allowed):
    v = data.get(key)
    if v not in allowed:
        bad()
    return v


def opt_enum(data, key, allowed, default=None):
    if key not in data or data[key] is None:
        return default
    return req_enum(data, key, allowed)


def _as_int(v):
    if isinstance(v, bool) or not isinstance(v, int):
        bad()
    return v


def req_int(data, key, minimum=None, maximum=None):
    if key not in data:
        bad()
    v = _as_int(data[key])
    if minimum is not None and v < minimum:
        bad()
    if maximum is not None and v > maximum:
        bad()
    return v


def opt_int(data, key, default=None, minimum=None, maximum=None, allow_null=True):
    if key not in data or data[key] is None:
        if key in data and data[key] is None and not allow_null:
            bad()
        return default
    return req_int(data, key, minimum, maximum)


def opt_bool(data, key, default):
    if key not in data or data[key] is None:
        return default
    v = data[key]
    if not isinstance(v, bool):
        bad()
    return v


def pagination():
    args = request.args
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad()
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            bad()
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad()
        if offset < 0:
            bad()
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
