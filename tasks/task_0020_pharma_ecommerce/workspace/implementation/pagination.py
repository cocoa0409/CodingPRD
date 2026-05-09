"""Pagination helpers — limit (default 10, min 1, max 100), offset (default 0)."""

from __future__ import annotations

from flask import request

from errors import err

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_limit_offset() -> tuple[int, int]:
    try:
        limit_raw = request.args.get("limit", default=None)
        offset_raw = request.args.get("offset", default=None)
        limit = int(limit_raw) if limit_raw is not None else DEFAULT_LIMIT
        offset = int(offset_raw) if offset_raw is not None else DEFAULT_OFFSET
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "limit/offset must be integers.")
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise err(
            "ERR_INVALID_REQUEST",
            f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}.",
        )
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def paginate(rows: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(rows)
    return rows[offset : offset + limit], total
