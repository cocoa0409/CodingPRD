"""Pagination parameter parsing helpers."""
from __future__ import annotations
from flask import request

from core.errors import raise_error

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination() -> tuple[int, int]:
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise_error("ERR_VALIDATION", "limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise_error("ERR_VALIDATION", f"limit must be in [{MIN_LIMIT}, {MAX_LIMIT}].")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise_error("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            raise_error("ERR_VALIDATION", "offset must be >= 0.")
    return limit, offset


def page(items: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(items)
    return items[offset : offset + limit], total
