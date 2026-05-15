"""Pagination parameter parsing per PRD §2.3."""
from __future__ import annotations

from flask import request

from .errors import ApiError


def parse_limit_offset() -> tuple[int, int]:
    """`limit` default 10, range [1,100]; `offset` default 0, min 0."""
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", f"Invalid limit: {limit_raw!r}")
    try:
        offset = int(offset_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", f"Invalid offset: {offset_raw!r}")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", "limit must be in [1,100].")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", "offset must be >= 0.")
    return limit, offset
