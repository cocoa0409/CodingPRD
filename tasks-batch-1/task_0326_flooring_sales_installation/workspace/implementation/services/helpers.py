"""Shared request-parsing, pagination, and field-validation helpers."""
from flask import request

from errors import err

# Pagination defaults (response_envelope.pagination_defaults).
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

CATEGORIES = {"HARDWOOD", "LVP", "TILE", "CARPET"}


def body():
    """Return the parsed JSON body as a dict. Malformed/non-object -> 422."""
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def require_fields(data, fields):
    """Ensure every named field is present and non-null. Missing -> 422."""
    for f in fields:
        if data.get(f) is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def pagination():
    """Parse limit/offset query params with bounds. Out-of-bound -> 422."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_v = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit_v = int(limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit_v < PAGE_LIMIT_MIN or limit_v > PAGE_LIMIT_MAX:
            raise err(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d." % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX),
            )
    if offset is None:
        offset_v = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset_v = int(offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset_v < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit_v, offset_v


def paginate(items, limit, offset):
    """Sort already done by caller; slice the list and return (page, total)."""
    total = len(items)
    page = items[offset : offset + limit]
    return page, total


def sort_by_created(items):
    """Return items sorted by created_at ascending (stable)."""
    return sorted(items, key=lambda r: r["created_at"])


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_positive_number(data, field):
    v = data.get(field)
    if not is_number(v) or v <= 0:
        raise err("ERR_INVALID_REQUEST", "%s must be a number > 0." % field)
    return v


def require_nonneg_number(data, field):
    v = data.get(field)
    if not is_number(v) or v < 0:
        raise err("ERR_INVALID_REQUEST", "%s must be a number >= 0." % field)
    return v


def require_int_min(data, field, minimum):
    v = data.get(field)
    if not is_int(v) or v < minimum:
        raise err("ERR_INVALID_REQUEST", "%s must be an integer >= %d." % (field, minimum))
    return v
