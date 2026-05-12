"""Pagination helpers."""
from flask import request

from errors import ERR_INVALID_INPUT, err


def parse_pagination():
    args = request.args
    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_INPUT, "limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_INPUT, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err(ERR_INVALID_INPUT, "limit must be in [1, 100]")
    if offset < 0:
        raise err(ERR_INVALID_INPUT, "offset must be >= 0")
    return limit, offset


def slice_sorted(rows, limit, offset, sort_key="created_at"):
    """Sort by created_at ascending, then slice. Returns (page_items, total_count)."""
    sortable = sorted(rows, key=lambda r: (r.get(sort_key) or "", r.get("id", "")))
    total = len(sortable)
    return sortable[offset:offset + limit], total
