"""Pagination helpers — defaults per SCAFFOLD pagination_defaults."""

from flask import request

from .errors import APIError


DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination():
    """Return (limit, offset) parsed from query string with bounds enforcement."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise APIError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise APIError("ERR_INVALID_REQUEST", "limit out of range.")

    if raw_offset is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise APIError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise APIError("ERR_INVALID_REQUEST", "offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
