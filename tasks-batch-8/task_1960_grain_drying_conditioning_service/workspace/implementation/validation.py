"""Request-shape validation helpers (priority 5, ERR_INVALID_REQUEST)."""

from flask import request

from db import parse_date, parse_datetime
from errors import raise_err


def _bad(msg):
    raise_err("ERR_INVALID_REQUEST", msg)


def get_body():
    """JSON object body; missing/invalid JSON or non-object -> 400.

    Action endpoints with no declared input tolerate an empty body.
    """
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        _bad("Request body must be a JSON object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_field(body, field):
    if field not in body or body[field] is None:
        _bad("Missing required field: %s" % field)
    return body[field]


def req_str(body, field):
    v = req_field(body, field)
    if not isinstance(v, str) or not v.strip():
        _bad("Field %s must be a non-empty string" % field)
    return v


def req_int(body, field, minimum=None):
    v = req_field(body, field)
    if not is_int(v):
        _bad("Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        _bad("Field %s must be >= %s" % (field, minimum))
    return v


def req_num(body, field, minimum=None, maximum=None, exclusive_min=False, exclusive_max=False):
    v = req_field(body, field)
    if not is_num(v):
        _bad("Field %s must be a number" % field)
    if minimum is not None:
        if exclusive_min and not v > minimum:
            _bad("Field %s must be > %s" % (field, minimum))
        if not exclusive_min and not v >= minimum:
            _bad("Field %s must be >= %s" % (field, minimum))
    if maximum is not None:
        if exclusive_max and not v < maximum:
            _bad("Field %s must be < %s" % (field, maximum))
        if not exclusive_max and not v <= maximum:
            _bad("Field %s must be <= %s" % (field, maximum))
    return v


def req_enum(body, field, allowed):
    v = req_field(body, field)
    if not isinstance(v, str) or v not in allowed:
        _bad("Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def opt_int(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not is_int(v):
        _bad("Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        _bad("Field %s must be >= %s" % (field, minimum))
    return v


def opt_num(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not is_num(v):
        _bad("Field %s must be a number" % field)
    if minimum is not None and v < minimum:
        _bad("Field %s must be >= %s" % (field, minimum))
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        _bad("Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        _bad("Field %s must be a boolean" % field)
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        _bad("Field %s must be a string" % field)
    return v


def req_date(body, field):
    v = req_field(body, field)
    d = parse_date(v)
    if d is None or len(v) != 10:
        _bad("Field %s must be a YYYY-MM-DD date" % field)
    return v


def req_datetime(body, field):
    v = req_field(body, field)
    if parse_datetime(v) is None:
        _bad("Field %s must be an ISO 8601 datetime" % field)
    return v


def parse_pagination(args):
    """limit/offset per PRD §2.3: default 10/0, limit min 1 max 100."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def paginate(records, args):
    """Slice a creation-sorted list; returns (page, pagination-meta)."""
    limit, offset = parse_pagination(args)
    total = len(records)
    page = records[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
