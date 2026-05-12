"""Pagination parameter parsing."""
from __future__ import annotations

from flask import request

from errors import raise_error


def parse_pagination() -> tuple[int, int]:
    """Return (limit, offset) with default values from PRD §2.3."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (ValueError, TypeError):
        raise_error("ERR_BAD_REQUEST", "limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (ValueError, TypeError):
        raise_error("ERR_BAD_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_error("ERR_BAD_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        raise_error("ERR_BAD_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(items)
    return items[offset: offset + limit], total
