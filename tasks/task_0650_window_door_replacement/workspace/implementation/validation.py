"""Shared validation helpers: pagination parsing and request body field checks."""
from flask import request

import errors

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def parse_pagination():
    """Parse limit/offset query params. Raises ERR_VALIDATION_LIMIT when out of
    range (limit outside [1,100] or offset negative)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_VALIDATION_LIMIT, "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise errors.err(errors.ERR_VALIDATION_LIMIT, "limit must be between 1 and 100")

    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_VALIDATION_LIMIT, "offset must be an integer")
        if offset < 0:
            raise errors.err(errors.ERR_VALIDATION_LIMIT, "offset must be non-negative")

    return limit, offset


def paginate(items, limit, offset):
    """items already sorted. Returns (page, pagination_meta)."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sort_by_created(items):
    # created_at ascending; ties broken by id for determinism.
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))


def get_body():
    """Return the JSON body as a dict, or raise ERR_INVALID_REQUEST if malformed."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, "missing required field: %s" % f)


def require_string(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be a non-empty string" % field)
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if val not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be one of %s" % (field, sorted(allowed)))
    return val


def require_positive_number(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be a number" % field)
    if val <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be greater than 0" % field)
    return val


def require_positive_int(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be an integer" % field)
    if val <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be greater than 0" % field)
    return val
