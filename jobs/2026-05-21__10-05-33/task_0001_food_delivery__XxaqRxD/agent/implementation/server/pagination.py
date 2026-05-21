from __future__ import annotations

from typing import Iterable

from flask import request

from .errors import ApiError


def parse_pagination() -> tuple[int, int]:
    try:
        limit_s = request.args.get("limit", "10")
        offset_s = request.args.get("offset", "0")
        limit = int(limit_s)
        offset = int(offset_s)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", "offset must be non-negative")
    return limit, offset


def page_slice(rows: Iterable[dict], *, limit: int, offset: int) -> tuple[list[dict], int]:
    """Sort by created_at ascending then slice."""
    sorted_rows = sorted(rows, key=lambda r: (r["created_at"], r["id"]))
    total = len(sorted_rows)
    return sorted_rows[offset : offset + limit], total
