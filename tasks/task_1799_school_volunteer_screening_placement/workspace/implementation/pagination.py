"""Pagination helpers per PRD §2.3 and scaffold response_envelope.

limit default 10, min 1, max 100; offset default 0. Sort: created_at ascending.
"""

from flask import request

from errors import invalid_request


def parse_pagination():
    """Parse and validate limit/offset query params."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending, then apply offset/limit. Returns (page, total)."""
    items = sorted(items, key=lambda e: (e.get("created_at", ""), e.get("id", "")))
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
