"""Pagination parsing for list endpoints."""
from __future__ import annotations

from flask import request

from .errors import ApiError


def parse() -> tuple[int, int]:
    """Return (limit, offset). Raises ERR_VALIDATION when out of range."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except ValueError:
        raise ApiError("ERR_VALIDATION", "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", "limit must be in [1,100]")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def apply(items: list, limit: int, offset: int, *, sort_key: str = "created_at"):
    """Sort + slice + report total_count."""
    sorted_items = sorted(items, key=lambda x: x[sort_key])
    total = len(sorted_items)
    window = sorted_items[offset:offset + limit]
    return window, total
