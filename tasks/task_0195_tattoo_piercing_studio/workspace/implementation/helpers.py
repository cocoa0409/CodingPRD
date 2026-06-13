"""Request-parsing, pagination, and validation helpers."""
from flask import request

from errors import ApiError

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_json_body():
    """Return the parsed JSON body as a dict; {} when empty.

    A body that is present but not valid JSON, or JSON that is not an object,
    is rejected with ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return val


def require_int(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return val


def optional_int(body, field):
    if field not in body or body[field] is None:
        return None
    return require_int(body, field)


def require_bool(body, field):
    val = body.get(field)
    if not isinstance(val, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return val


def require_enum(body, field, members):
    val = body.get(field)
    if val not in members:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field %s must be one of %s" % (field, sorted(members)))
    return val


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3).

    limit defaults to 10, min 1, max 100; offset defaults to 0.
    Invalid (non-integer) values are rejected with ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT:
            limit = PAGINATION_MIN_LIMIT
        elif limit > PAGINATION_MAX_LIMIT:
            limit = PAGINATION_MAX_LIMIT

    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0

    return limit, offset


def paginate(items):
    """Sort by created_at asc (PRD §2.3), apply limit/offset, return
    (page, meta) where meta carries limit/offset/total_count/has_more."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
