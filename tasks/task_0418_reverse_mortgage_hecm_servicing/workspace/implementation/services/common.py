"""Shared request helpers: pagination, body parsing, lookups."""
from flask import request

import errors


def parse_pagination():
    """Read limit/offset query params with defaults and bounds (§2.3).
    Returns (limit, offset). Raises ERR_INVALID_PAGINATION on out-of-bounds."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_PAGINATION, "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_PAGINATION, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise errors.err(errors.ERR_INVALID_PAGINATION, "limit must be between 1 and 100")
    if offset < 0:
        raise errors.err(errors.ERR_INVALID_PAGINATION, "offset must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ascending (insertion order via _seq), window, and
    return (page, list_meta)."""
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    window = ordered[offset:offset + limit]
    list_meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return window, list_meta


def get_json_body():
    """Return the request JSON body as a dict (empty dict if none)."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def require_positive_int(body, field):
    """Require field present, an integer, and strictly > 0."""
    if field not in body or body[field] is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be an integer" % field)
    if val <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be greater than zero" % field)
    return val


def require_nonneg_int(body, field):
    if field not in body or body[field] is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be an integer" % field)
    if val < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be >= 0" % field)
    return val


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be an integer" % field)
    return val


def require_enum(body, field, allowed):
    if field not in body or body[field] is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    val = body[field]
    if val not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be one of %s" % (field, sorted(allowed)))
    return val
