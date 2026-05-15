"""List pagination helpers (PRD §2.3)."""
from __future__ import annotations

from typing import Any, List, Tuple

from flask import request

from app.errors import api_error


def parse_pagination() -> Tuple[int, int]:
    """Return (limit, offset). Raises ERR_INVALID_REQUEST on bad values."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise api_error("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise api_error("ERR_INVALID_REQUEST", "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise api_error("ERR_INVALID_REQUEST", "offset must be a non-negative integer")
        if offset < 0:
            raise api_error("ERR_INVALID_REQUEST", "offset must be a non-negative integer")

    return limit, offset


def sort_by_created_at(items: List[dict]) -> List[dict]:
    return sorted(items, key=lambda x: (x.get("created_at", ""), x.get("id", "")))


def paginate(items: List[Any], limit: int, offset: int) -> Tuple[List[Any], int]:
    total = len(items)
    return items[offset : offset + limit], total
