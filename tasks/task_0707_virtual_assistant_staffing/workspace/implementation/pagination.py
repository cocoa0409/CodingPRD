"""Pagination parsing + application (PRD §2.3).

limit default 10, in [1,100]; offset default 0, >= 0. Out-of-range ->
ERR_PAGINATION_INVALID (422). Results ordered by created_at ASC (oldest first);
ties broken by hidden insertion sequence (_seq) for a stable total order.
"""
from flask import request

from errors import err

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _parse_int(raw, name):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err("ERR_PAGINATION_INVALID", f"{name} must be an integer")


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = LIMIT_DEFAULT if raw_limit is None else _parse_int(raw_limit, "limit")
    offset = OFFSET_DEFAULT if raw_offset is None else _parse_int(raw_offset, "offset")
    if limit < LIMIT_MIN or limit > LIMIT_MAX:
        raise err("ERR_PAGINATION_INVALID", "limit must be in [1,100]")
    if offset < 0:
        raise err("ERR_PAGINATION_INVALID", "offset must be >= 0")
    return limit, offset


def order_and_page(records, limit, offset):
    """Sort by created_at ASC (stable via _seq), then window. Returns
    (page_records, total_count)."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
