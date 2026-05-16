"""Pagination helpers for list endpoints."""

from flask import request

from config import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from errors import APIError


def get_pagination():
    """Return (limit, offset) tuple parsed from query string."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise APIError("ERR_VALIDATION", "Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise APIError(
                "ERR_VALIDATION",
                f"Query parameter 'limit' must be between {PAGINATION_MIN_LIMIT} and {PAGINATION_MAX_LIMIT}.",
            )

    if raw_offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise APIError("ERR_VALIDATION", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise APIError("ERR_VALIDATION", "Query parameter 'offset' must be non-negative.")

    return limit, offset


def slice_items(items, limit, offset):
    """Apply offset/limit to a list."""
    return items[offset : offset + limit]
