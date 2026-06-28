"""Request parsing, pagination, and field validation helpers."""
from flask import request

from errors import err


def get_json():
    """Return the request JSON body as a dict (empty dict if none)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "body must be a JSON object")
    return data


def parse_pagination():
    """PRD 2.3: limit default 10 (1..100), offset default 0 (>=0).

    Out-of-range -> ERR_VALIDATION_PAGINATION (422)."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION_PAGINATION", "invalid limit")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION_PAGINATION", "limit out of range")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION_PAGINATION", "invalid offset")
        if offset < 0:
            raise err("ERR_VALIDATION_PAGINATION", "offset out of range")

    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    window = items[offset:offset + limit]
    return window, total


def require_fields(body, names):
    for n in names:
        if body.get(n) is None:
            raise err("ERR_INVALID_REQUEST", "missing required field: %s" % n)


def require_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "field %s must be a non-empty string" % name)
    return v


def opt_str(body, name, default=None):
    if name not in body or body.get(name) is None:
        return default
    v = body.get(name)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "field %s must be a string" % name)
    return v


def require_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "field %s must be an integer" % name)
    return v


def opt_int(body, name, default):
    if name not in body or body.get(name) is None:
        return default
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "field %s must be an integer" % name)
    return v


def require_number(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "field %s must be a number" % name)
    return v


def opt_number(body, name, default):
    if name not in body or body.get(name) is None:
        return default
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "field %s must be a number" % name)
    return v


def opt_bool(body, name, default):
    if name not in body or body.get(name) is None:
        return default
    v = body.get(name)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "field %s must be a boolean" % name)
    return v


def require_enum(body, name, allowed):
    v = body.get(name)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", "field %s must be one of %s" % (name, allowed))
    return v
