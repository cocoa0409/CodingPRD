"""Request-shape validation (ERR_INVALID_REQUEST, evaluated before all ordered
checks per PRD 2.7), path/body reference resolution (ERR_NOT_FOUND), pagination
and query-filter parsing (PRD 2.3)."""
from datetime import datetime

from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def req_bool(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid boolean field: {field}")
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= {minimum}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def _validate_datetime(v, field):
    s = v.strip()
    try:
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO 8601 datetime: {field}")


def req_datetime(body, field):
    v = req_str(body, field)
    _validate_datetime(v, field)
    return v


def require_path(collection, rid):
    """Path-parameter existence (step 3), resolved left to right."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"resource not found: {rid}")
    return obj


def require_ref(collection, rid, field):
    """Body-referenced foreign-key existence (step 4)."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{field} does not resolve: {rid}")
    return obj


def pagination_params():
    """limit/offset per PRD 2.3: default 10 / 0, limit within [1, 100]."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be within [1, 100]")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def opt_query_str(name):
    return request.args.get(name)


def opt_query_enum(name, allowed):
    v = request.args.get(name)
    if v is None:
        return None
    if v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"invalid value for query filter: {name}")
    return v


def opt_query_bool(name):
    v = request.args.get(name)
    if v is None:
        return None
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    raise_error(ERR_INVALID_REQUEST, f"invalid boolean for query filter: {name}")


def paginate(records, limit, offset):
    """Ascending creation-timestamp order (PRD 2.3); stable sort keeps insertion
    order for ties created at the same logical-clock instant."""
    ordered = sorted(records, key=lambda r: r["created_at"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
