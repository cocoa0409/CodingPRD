"""Pagination helper for list endpoints.

Params: limit (default 10, min 1, max 100), offset (default 0).
Sort by created_at ascending (tiebreak by creation sequence).
Meta carries: limit, offset, total_count, has_more.
"""
from flask import request

from errors import err


def _parse_int_param(name, default, minimum=None, maximum=None, clamp_max=False):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"Query param {name} must be an integer.")
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", f"Query param {name} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        if clamp_max:
            value = maximum
        else:
            raise err("ERR_INVALID_REQUEST", f"Query param {name} must be <= {maximum}.")
    return value


def paginate(records):
    """Sort records by created sequence, apply limit/offset, return (page, meta)."""
    limit = _parse_int_param("limit", 10, minimum=1, maximum=100)
    offset = _parse_int_param("offset", 0, minimum=0)

    ordered = sorted(records, key=lambda r: (r.get("created_at"), r.get("_seq", 0)))
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
