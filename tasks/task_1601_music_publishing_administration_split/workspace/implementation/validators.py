"""Request body / query validation helpers (tier-4 request shape)."""
from flask import request

import db
from errors import ApiError, ERR_VALIDATION

_MISSING = object()


def _fail(msg):
    raise ApiError(ERR_VALIDATION, 422, msg)


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        _fail("request body must be a JSON object")
    return data


def req_str(body, name):
    v = body.get(name, _MISSING)
    if v is _MISSING or v is None or not isinstance(v, str) or v == "":
        _fail("field '%s' is required and must be a non-empty string" % name)
    return v


def opt_str(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        _fail("field '%s' must be a string" % name)
    return v


def req_int(body, name, lo=None, hi=None):
    v = body.get(name, _MISSING)
    if v is _MISSING or v is None or isinstance(v, bool) or not isinstance(v, int):
        _fail("field '%s' is required and must be an integer" % name)
    if lo is not None and v < lo:
        _fail("field '%s' must be >= %d" % (name, lo))
    if hi is not None and v > hi:
        _fail("field '%s' must be <= %d" % (name, hi))
    return v


def opt_int(body, name, lo=None, hi=None):
    v = body.get(name)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        _fail("field '%s' must be an integer" % name)
    if lo is not None and v < lo:
        _fail("field '%s' must be >= %d" % (name, lo))
    if hi is not None and v > hi:
        _fail("field '%s' must be <= %d" % (name, hi))
    return v


def req_enum(body, name, allowed):
    v = body.get(name, _MISSING)
    if v is _MISSING or v is None or not isinstance(v, str) or v not in allowed:
        _fail("field '%s' must be one of: %s" % (name, ", ".join(allowed)))
    return v


def req_dt(body, name):
    v = body.get(name, _MISSING)
    if v is _MISSING or v is None:
        _fail("field '%s' is required" % name)
    dt = db.parse_dt(v)
    if dt is None:
        _fail("field '%s' must be an ISO 8601 datetime" % name)
    return dt


def opt_dt(body, name):
    v = body.get(name)
    if v is None:
        return None
    dt = db.parse_dt(v)
    if dt is None:
        _fail("field '%s' must be an ISO 8601 datetime" % name)
    return dt


def req_list(body, name, non_empty=False):
    v = body.get(name, _MISSING)
    if v is _MISSING or v is None or not isinstance(v, list):
        _fail("field '%s' is required and must be an array" % name)
    if non_empty and len(v) == 0:
        _fail("field '%s' must be a non-empty array" % name)
    return v


def opt_list(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, list):
        _fail("field '%s' must be an array" % name)
    return v


def req_str_list(body, name, non_empty=False, allowed=None):
    items = req_list(body, name, non_empty=non_empty)
    for item in items:
        if not isinstance(item, str):
            _fail("field '%s' must contain only strings" % name)
        if allowed is not None and item not in allowed:
            _fail("field '%s' contains an unsupported value" % name)
    return items


def pagination_params():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _fail("limit must be an integer")
        if limit < 1 or limit > 100:
            _fail("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _fail("offset must be an integer")
        if offset < 0:
            _fail("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
