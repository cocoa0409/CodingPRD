"""Pagination parameter parsing per PRD §2.3."""
from __future__ import annotations

from typing import Any, Optional

from flask import request

from .errors import ApiError


def parse_limit_offset() -> tuple[int, int]:
    """Read `limit` and `offset` query params; defaults limit=10, offset=0; min/max enforced."""
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_PAGINATION_INVALID", f"Invalid limit: {limit_raw!r}")
    try:
        offset = int(offset_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_PAGINATION_INVALID", f"Invalid offset: {offset_raw!r}")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_PAGINATION_INVALID", f"limit must be 1..100, got {limit}")
    if offset < 0:
        raise ApiError("ERR_PAGINATION_INVALID", f"offset must be >= 0, got {offset}")
    return limit, offset


def parse_optional_str(key: str) -> Optional[str]:
    v = request.args.get(key)
    if v is None or v == "":
        return None
    return v


def paginate(items: list[Any], limit: int, offset: int) -> tuple[list[Any], dict[str, Any]]:
    """Slice a list by limit/offset, returning the slice + pagination metadata."""
    total = len(items)
    sliced = items[offset : offset + limit]
    return sliced, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
