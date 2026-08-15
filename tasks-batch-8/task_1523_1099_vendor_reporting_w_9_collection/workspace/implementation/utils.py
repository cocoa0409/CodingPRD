from datetime import datetime, timezone
from flask import request
from errors import ApiError


def parse_dt(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be an ISO8601 datetime string" % field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' is not a valid ISO8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def json_body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def reject_unknown(b, allowed):
    extra = [k for k in b if k not in allowed]
    if extra:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Unknown field(s): %s" % ", ".join(sorted(extra)))


def req_str(b, name, allow_empty=False):
    if name not in b or b[name] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field '%s'" % name)
    v = b[name]
    if not isinstance(v, str) or (not allow_empty and not v.strip()):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be a non-empty string" % name)
    return v


def opt_str(b, name):
    v = b.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be a string" % name)
    return v


def req_int(b, name):
    if name not in b or b[name] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field '%s'" % name)
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be an integer" % name)
    return v


def opt_int(b, name, default=None):
    v = b.get(name)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be an integer" % name)
    return v


def opt_bool(b, name, default=None):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be a boolean" % name)
    return v


def req_enum(b, name, members):
    v = req_str(b, name)
    if v not in members:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be one of %s" % (name, sorted(members)))
    return v


def opt_enum(b, name, members, default=None):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, str) or v not in members:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be one of %s" % (name, sorted(members)))
    return v


def list_page(items):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": offset + len(page) < total}
    return page, pagination
