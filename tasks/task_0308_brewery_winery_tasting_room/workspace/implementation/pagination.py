"""List pagination (PRD §2.3): limit default 10 (min 1, max 100), offset default 0.
Results sorted by creation timestamp ascending. Pagination fields go in meta."""
from flask import request

from errors import err, ERR_INVALID_REQUEST


def _parse_int_param(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, f"Query param {name} must be an integer")


def paginate(items):
    """items: full list already sorted ascending by creation order.

    Returns (page_items, pagination_meta).
    """
    limit = _parse_int_param("limit", 10)
    offset = _parse_int_param("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total_count = len(items)
    page = items[offset:offset + limit]
    pagination_meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + limit < total_count,
    }
    return page, pagination_meta


def sorted_by_creation(values):
    """Sort an iterable of entities by creation order (ascending)."""
    return sorted(values, key=lambda e: e.get("_seq", 0))
