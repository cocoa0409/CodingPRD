"""Pagination helpers — limit/offset per PRD §2.3."""
from __future__ import annotations

from typing import Any, List, Tuple

from flask import request

from core.errors import err_validation_failed


DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _parse_int(name: str, raw: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err_validation_failed(f"{name} must be an integer.")


def parse_pagination() -> Tuple[int, int]:
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None or limit_raw == "":
        limit = DEFAULT_LIMIT
    else:
        limit = _parse_int("limit", limit_raw)
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err_validation_failed(
                f"limit must be in [{MIN_LIMIT}, {MAX_LIMIT}]."
            )

    if offset_raw is None or offset_raw == "":
        offset = DEFAULT_OFFSET
    else:
        offset = _parse_int("offset", offset_raw)
        if offset < 0:
            raise err_validation_failed("offset must be >= 0.")

    return limit, offset


def paginate(items: List[Any], limit: int, offset: int) -> Tuple[List[Any], dict]:
    total = len(items)
    sliced = items[offset : offset + limit]
    return sliced, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
