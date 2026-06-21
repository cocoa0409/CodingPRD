"""Request-body field validation (ERR_INVALID_REQUEST, HTTP 422, PRD §2.6 tier 4)."""
from errors import err
from util import parse_dt


def get_body():
    """Return the JSON body as a dict, or {} when absent. A body that is present
    but not a JSON object is an ERR_INVALID_REQUEST."""
    from flask import request

    if request.content_length in (None, 0) and not (request.data or b"").strip():
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # Empty body is acceptable for action endpoints with no required fields.
        if not (request.data or b"").strip():
            return {}
        err("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if not isinstance(data, dict):
        err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        err("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string" % name)
    return v


def require_enum(body, name, members):
    v = body.get(name)
    if not isinstance(v, str) or v not in members:
        err("ERR_INVALID_REQUEST", "Field '%s' must be one of %s" % (name, sorted(members)))
    return v


def optional_enum(body, name, members, default=None):
    if name not in body or body.get(name) is None:
        return default
    return require_enum(body, name, members)


def require_int(body, name, minimum=None, maximum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", "Field '%s' must be an integer" % name)
    if minimum is not None and v < minimum:
        err("ERR_INVALID_REQUEST", "Field '%s' must be >= %d" % (name, minimum))
    if maximum is not None and v > maximum:
        err("ERR_INVALID_REQUEST", "Field '%s' must be <= %d" % (name, maximum))
    return v


def require_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        err("ERR_INVALID_REQUEST", "Field '%s' must be a boolean" % name)
    return v


def optional_bool(body, name, default=False):
    if name not in body or body.get(name) is None:
        return default
    return require_bool(body, name)


def require_string_array(body, name):
    v = body.get(name)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        err("ERR_INVALID_REQUEST", "Field '%s' must be an array of strings" % name)
    return v


def require_datetime(body, name):
    raw = body.get(name)
    dt = parse_dt(raw)
    if dt is None:
        err("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 datetime" % name)
    return dt


def require_zip(body, name):
    v = require_str(body, name)
    if len(v) != 5 or not v.isdigit():
        err("ERR_INVALID_REQUEST", "Field '%s' must be a 5-digit ZIP string" % name)
    return v


def parse_pagination(args):
    """Parse and bound-check limit/offset (PRD §2.3). Defaults limit=10, offset=0;
    limit must be 1..100, offset >= 0; otherwise ERR_INVALID_REQUEST."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset
