"""Request-shape validation helpers (validation cascade priority 5) and pagination."""
from flask import request

from errors import ApiError

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def get_body():
    """Parse the JSON request body; an absent body is treated as {} (for optional-field POSTs)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object", 400)
    return data


def _bad(msg):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def req_str(data, name):
    v = data.get(name)
    if not isinstance(v, str):
        raise _bad("Field '%s' is required and must be a string" % name)
    return v


def opt_str(data, name):
    v = data.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise _bad("Field '%s' must be a string" % name)
    return v


def req_bool(data, name):
    v = data.get(name)
    if not isinstance(v, bool):
        raise _bad("Field '%s' is required and must be a boolean" % name)
    return v


def opt_bool(data, name, default=None):
    v = data.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise _bad("Field '%s' must be a boolean" % name)
    return v


def req_int(data, name):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise _bad("Field '%s' is required and must be an integer" % name)
    return v


def req_number(data, name):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise _bad("Field '%s' is required and must be a number" % name)
    return v


def req_enum(data, name, allowed):
    v = data.get(name)
    if not isinstance(v, str) or v not in allowed:
        raise _bad("Field '%s' must be one of %s" % (name, sorted(allowed)))
    return v


def opt_enum(data, name, allowed, default=None):
    v = data.get(name)
    if v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        raise _bad("Field '%s' must be one of %s" % (name, sorted(allowed)))
    return v


def pagination_params():
    """Read limit/offset query params per PRD §2.3 (default 10/0, limit in [1,100], offset >= 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = LIMIT_DEFAULT if raw_limit is None else int(raw_limit)
    except (TypeError, ValueError):
        raise _bad("Query parameter 'limit' must be an integer")
    try:
        offset = OFFSET_DEFAULT if raw_offset is None else int(raw_offset)
    except (TypeError, ValueError):
        raise _bad("Query parameter 'offset' must be an integer")
    if limit < LIMIT_MIN or limit > LIMIT_MAX:
        raise _bad("Query parameter 'limit' must be between 1 and 100")
    if offset < 0:
        raise _bad("Query parameter 'offset' must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items must already be filtered and sorted; returns (page, total_count)."""
    total = len(items)
    return items[offset:offset + limit], total


def sort_by_creation(records):
    """PRD §2.3: ascending creation timestamp; insertion sequence breaks ties."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
