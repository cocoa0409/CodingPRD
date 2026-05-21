"""Pagination helpers, honoring scaffold defaults (limit=10, offset=0, max=100)."""
from __future__ import annotations

from typing import Any, Iterable, List, Tuple

from flask import request

from core.errors import err_pagination_invalid


DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _parse_int(name: str, raw: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err_pagination_invalid(f"{name} must be an integer.")


def parse_pagination() -> Tuple[int, int]:
    """Parse and validate `limit` and `offset` query params."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = DEFAULT_LIMIT
    else:
        if limit_raw == "":
            raise err_pagination_invalid("limit must not be empty.")
        limit = _parse_int("limit", limit_raw)
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err_pagination_invalid(
                f"limit must be in [{MIN_LIMIT}, {MAX_LIMIT}]."
            )

    if offset_raw is None:
        offset = DEFAULT_OFFSET
    else:
        if offset_raw == "":
            raise err_pagination_invalid("offset must not be empty.")
        offset = _parse_int("offset", offset_raw)
        if offset < 0:
            raise err_pagination_invalid("offset must be >= 0.")

    return limit, offset


def paginate(items: List[Any], limit: int, offset: int) -> Tuple[List[Any], dict]:
    total = len(items)
    sliced = items[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return sliced, meta
