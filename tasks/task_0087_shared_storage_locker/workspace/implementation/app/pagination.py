"""Pagination parameter parsing per PRD §2.3."""
from __future__ import annotations

from typing import Optional

from flask import request

from .errors import ApiError


def parse_limit_offset() -> tuple[int, int]:
    """Read `limit` and `offset` from query params with PRD §2.3 defaults."""
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_BAD_REQUEST", f"Invalid limit: {limit_raw!r}")
    try:
        offset = int(offset_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_BAD_REQUEST", f"Invalid offset: {offset_raw!r}")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def parse_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ApiError("ERR_BAD_REQUEST", f"Invalid int: {value!r}")
