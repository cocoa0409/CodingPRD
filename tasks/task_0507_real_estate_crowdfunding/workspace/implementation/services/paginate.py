"""Pagination (PRD §2.3): limit default 10 min 1 max 100; offset default 0.

List results ordered by creation timestamp ascending (use _seq for stability).
"""
from flask import request

from errors import err

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _parse_int(name, raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", f"Query parameter {name} must be an integer")


def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = DEFAULT_LIMIT
    else:
        limit = _parse_int("limit", limit_raw)
        if limit < MIN_LIMIT:
            limit = MIN_LIMIT
        elif limit > MAX_LIMIT:
            limit = MAX_LIMIT

    if offset_raw is None:
        offset = DEFAULT_OFFSET
    else:
        offset = _parse_int("offset", offset_raw)
        if offset < 0:
            offset = 0

    return limit, offset


def order_and_page(items, limit, offset):
    """Sort by creation order ascending (_seq), then slice."""
    ordered = sorted(items, key=lambda e: e["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
