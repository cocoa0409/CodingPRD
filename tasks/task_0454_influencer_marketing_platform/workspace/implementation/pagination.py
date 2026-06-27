"""Pagination (PRD 2.3). limit default 10, min 1, max 100; offset default 0.
Results sorted ascending by created_at (tie-broken by insertion seq)."""
from flask import request

from errors import err

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _parse_int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        v = int(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Query param %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Query param %s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", "Query param %s must be <= %s" % (name, maximum))
    return v


def paginate(rows):
    """rows is a list of records (dicts with created_at/_seq). Returns
    (page_rows, pagination_meta). Sorts ascending by created_at, then _seq."""
    limit = _parse_int_param("limit", DEFAULT_LIMIT, MIN_LIMIT, MAX_LIMIT)
    offset = _parse_int_param("offset", DEFAULT_OFFSET, 0, None)

    ordered = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = (offset + limit) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta
