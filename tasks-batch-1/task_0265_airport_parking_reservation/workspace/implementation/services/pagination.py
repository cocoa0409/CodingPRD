"""Pagination + sort helpers (PRD §2.3)."""
from flask import request

from errors import err

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _parse_int_param(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", f"Query parameter {name} must be an integer.")


def get_pagination():
    limit = _parse_int_param("limit")
    offset = _parse_int_param("offset")
    if limit is None:
        limit = DEFAULT_LIMIT
    else:
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err("ERR_VALIDATION", "limit must be between 1 and 100.")
    if offset is None:
        offset = DEFAULT_OFFSET
    else:
        if offset < 0:
            raise err("ERR_VALIDATION", "offset must be at least 0.")
    return limit, offset


def paginate(records):
    """Sort by created_at asc (stable via _seq), then page.

    Returns (page_items, total_count, limit, offset).
    """
    limit, offset = get_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total_count = len(ordered)
    page = ordered[offset : offset + limit]
    return page, total_count, limit, offset
