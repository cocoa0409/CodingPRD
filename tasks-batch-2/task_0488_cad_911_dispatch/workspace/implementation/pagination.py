"""Offset-based pagination (PRD §2.3, Scaffold Table 0).

limit defaults to 10, min 1, max 100; offset defaults to 0. Lists are sorted by
created_at ascending unless otherwise specified. Malformed pagination params are
clamped/ignored gracefully rather than erroring (they are query params, not body
fields subject to ERR_INVALID_REQUEST).
"""
from flask import request

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _parse_int(raw, default):
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def get_limit_offset():
    limit = _parse_int(request.args.get("limit"), DEFAULT_LIMIT)
    offset = _parse_int(request.args.get("offset"), DEFAULT_OFFSET)
    if limit < MIN_LIMIT:
        limit = MIN_LIMIT
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items):
    """items must already be sorted. Returns (page_items, limit, offset, total)."""
    limit, offset = get_limit_offset()
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sort_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["id"]))
