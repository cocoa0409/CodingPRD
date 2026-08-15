"""Request payload validation helpers.

Malformed payloads (missing/invalid required field, invalid enum, unknown
field, non-positive quantity) fail with ERR_INVALID_REQUEST (400).
"""

from flask import request

from db import parse_date
from errors import ApiError, ERR_INVALID_REQUEST


def _bad(msg):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def json_body():
    """Return the request JSON object; absent body counts as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        _bad("Request body must be a JSON object")
    return data


def no_unknown(data, allowed):
    extra = [k for k in data.keys() if k not in allowed]
    if extra:
        _bad("Unknown field: %s" % sorted(extra)[0])


def _present(data, name):
    if name not in data or data[name] is None:
        _bad("Missing required field: %s" % name)
    return data[name]


def req_str(data, name, allow_empty=False):
    v = _present(data, name)
    if not isinstance(v, str) or (not allow_empty and v.strip() == ""):
        _bad("Field %s must be a non-empty string" % name)
    return v


def req_int(data, name, min_val=None):
    v = _present(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad("Field %s must be an integer" % name)
    if min_val is not None and v < min_val:
        _bad("Field %s must be >= %s" % (name, min_val))
    return v


def opt_int(data, name, min_val=None):
    if name not in data or data[name] is None:
        return None
    return req_int(data, name, min_val)


def req_num(data, name, min_val=None):
    v = _present(data, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad("Field %s must be a number" % name)
    if v != v or v in (float("inf"), float("-inf")):
        _bad("Field %s must be a finite number" % name)
    if min_val is not None and v < min_val:
        _bad("Field %s must be >= %s" % (name, min_val))
    return v


def opt_num(data, name, min_val=None):
    if name not in data or data[name] is None:
        return None
    return req_num(data, name, min_val)


def req_bool(data, name):
    v = _present(data, name)
    if not isinstance(v, bool):
        _bad("Field %s must be a boolean" % name)
    return v


def opt_bool(data, name, default=False):
    if name not in data or data[name] is None:
        return default
    return req_bool(data, name)


def req_list(data, name):
    v = _present(data, name)
    if not isinstance(v, list):
        _bad("Field %s must be an array" % name)
    return v


def opt_list(data, name, default=None):
    if name not in data or data[name] is None:
        return list(default) if default is not None else None
    return req_list(data, name)


def req_enum(data, name, values):
    v = _present(data, name)
    if not isinstance(v, str) or v not in values:
        _bad("Field %s must be one of %s" % (name, sorted(values)))
    return v


def req_enum_list(data, name, values):
    items = req_list(data, name)
    for item in items:
        if not isinstance(item, str) or item not in values:
            _bad("Field %s contains an invalid value: %r" % (name, item))
    return items


def opt_enum_list(data, name, values, default=None):
    if name not in data or data[name] is None:
        return list(default) if default is not None else []
    return req_enum_list(data, name, values)


def req_date(data, name):
    from errors import ERR_INVALID_REQUEST  # local to avoid cycles in messages

    v = _present(data, name)
    d = parse_date(v)
    if d is None:
        _bad("Field %s must be a YYYY-MM-DD date" % name)
    return v, d  # raw string (for output) and parsed date


def req_str_list(data, name):
    items = req_list(data, name)
    for item in items:
        if not isinstance(item, str):
            _bad("Field %s must be an array of strings" % name)
    return items


def opt_str_list(data, name, default=None):
    if name not in data or data[name] is None:
        return list(default) if default is not None else []
    return req_str_list(data, name)


def parse_pagination(args):
    """limit (default 10, min 1, max 100) and offset (default 0, min 0)."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("limit must be an integer")
        if str(raw_limit).strip() != str(limit) and not str(raw_limit).strip().lstrip("+").isdigit():
            _bad("limit must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("offset must be an integer")
        if str(raw_offset).strip() != str(offset) and not str(raw_offset).strip().lstrip("+").isdigit():
            _bad("offset must be an integer")
        if offset < 0:
            _bad("offset must be >= 0")
    return limit, offset


def paginate(records, args):
    """records: already sorted list of raw record dicts (internal keys ok)."""
    from db import public

    limit, offset = parse_pagination(args)
    total = len(records)
    page = records[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return [public(r) for r in page], pagination
