from __future__ import annotations

"""Pagination param parsing and slicing."""
from flask import request

import errors as E


DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_limit_offset() -> tuple[int, int]:
    """Read limit/offset from query string with defaults + bounds.

    Reject malformed values with ERR_INVALID_REQUEST (the lowest-priority rule per §2.7).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise E.APIError(E.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise E.APIError(
                E.ERR_INVALID_REQUEST,
                f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}",
            )

    if offset_raw is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise E.APIError(E.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise E.APIError(E.ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def sort_by_created_at(rows: list[dict]) -> list[dict]:
    """Sort by created_at asc, ties broken by insertion order (never id)."""
    return sorted(rows, key=lambda r: (r["created_at"], r.get("_insertion_seq", 0)))


def slice_page(rows: list[dict], limit: int, offset: int) -> tuple[list[dict], int]:
    total = len(rows)
    return rows[offset:offset + limit], total
