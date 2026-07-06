"""Pagination helpers per PRD §2.3."""
from __future__ import annotations
from flask import request

from errors import ERR_INVALID_REQUEST, raise_error


def parse_limit_offset() -> tuple[int, int]:
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_REQUEST, "limit/offset must be integers")
        return 0, 0  # unreachable
    if limit < 1 or limit > 100:
        raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    """Sort by created_at ASC and slice.

    Tiebreak on `_seq` — the monotonic insertion counter stamped by
    stamp_common — so that entities created back-to-back at the same
    logical-clock instant preserve creation order.
    """
    ordered = sorted(items, key=lambda x: (x.get("created_at", ""), x.get("_seq", 0)))
    total = len(ordered)
    return ordered[offset : offset + limit], total
