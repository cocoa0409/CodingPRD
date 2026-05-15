"""Pagination parameter parsing per PRD §2.3."""
from __future__ import annotations

from typing import Optional

from flask import request

from .errors import ApiError


def parse_limit_offset() -> tuple[int, int]:
    """Read `limit` and `offset` from query params. Reject when outside [1,100] / >=0."""
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_PAGINATION", f"Invalid limit: {limit_raw!r}")
    try:
        offset = int(offset_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_PAGINATION", f"Invalid offset: {offset_raw!r}")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_PAGINATION", f"Limit out of range: {limit}")
    if offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION", f"Offset out of range: {offset}")
    return limit, offset


def parse_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_PAGINATION", f"Invalid int: {value!r}")
