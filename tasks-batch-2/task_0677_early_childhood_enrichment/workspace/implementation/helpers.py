"""Request-level helpers: pagination, typed body-field extraction, existence."""
from flask import request

import errors
from util import get_body  # re-export


def paginate(items):
    """Apply limit/offset pagination (PRD 2.3). limit default 10, min 1, max 100;
    offset default 0. Returns (page_items, limit, offset, total_count).

    Invalid pagination params are treated as malformed requests.
    """
    limit = request.args.get("limit")
    offset = request.args.get("offset")

    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit_v < 1:
            limit_v = 1
        elif limit_v > 100:
            limit_v = 100

    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset_v < 0:
            offset_v = 0

    total = len(items)
    page = items[offset_v:offset_v + limit_v]
    return page, limit_v, offset_v, total


def sort_created(items):
    """Default list ordering: created_at ASC, stabilized by the creation seq."""
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing or invalid field: {field}")
    return v


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing or invalid integer field: {field}")
    return v


def optional_int(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Invalid integer field: {field}")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing or invalid enum field: {field}")
    return v
