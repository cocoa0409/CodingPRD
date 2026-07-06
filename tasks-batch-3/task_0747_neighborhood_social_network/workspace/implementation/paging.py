"""Pagination + list envelope helpers.

Defaults: limit=10 (min 1, max 100), offset=0.
Meta carries: limit, offset, total_count, has_more.
"""
from __future__ import annotations

from flask import request

from errors import InvalidRequest


def parse_pagination() -> tuple[int, int]:
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        raise InvalidRequest("limit must be an integer")
    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise InvalidRequest("offset must be an integer")
    if limit < 1 or limit > 100:
        raise InvalidRequest("limit must be between 1 and 100")
    if offset < 0:
        raise InvalidRequest("offset must be >= 0")
    return limit, offset


def apply_pagination(rows: list) -> tuple[list, dict]:
    limit, offset = parse_pagination()
    total = len(rows)
    sliced = rows[offset : offset + limit]
    has_more = (offset + limit) < total
    return sliced, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
