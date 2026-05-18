"""Shared route helpers — pagination parsing and pagination-meta building."""

from flask import request

from config import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from errors import make_error


def parse_pagination() -> tuple[int, int]:
    """Parse limit/offset query params per response_envelope.pagination_defaults."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else PAGINATION_DEFAULT_LIMIT
        offset = int(offset_raw) if offset_raw is not None else PAGINATION_DEFAULT_OFFSET
    except (TypeError, ValueError):
        raise make_error("ERR_BAD_REQUEST", "limit/offset must be integers.")
    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise make_error("ERR_BAD_REQUEST", "limit out of range.")
    if offset < 0:
        raise make_error("ERR_BAD_REQUEST", "offset must be >= 0.")
    return limit, offset


def build_pagination_meta(limit: int, offset: int, total_count: int) -> dict:
    return {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    }


def slice_and_sort(rows: list[dict], limit: int, offset: int, *, sort_key: str = "created_at") -> list[dict]:
    """Sort by `sort_key` ASC (with a stable secondary on id) and slice."""
    rows_sorted = sorted(rows, key=lambda r: (r.get(sort_key, ""), r.get("id", "")))
    return rows_sorted[offset: offset + limit]
