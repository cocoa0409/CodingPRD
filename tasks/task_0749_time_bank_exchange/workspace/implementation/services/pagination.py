"""Pagination helper — reads limit / offset with §2.3 defaults & bounds."""
from flask import request
from errors import raise_err, ERR_INVALID_REQUEST


def parse_pagination():
    """Return (limit, offset). Invalid values -> ERR_INVALID_REQUEST."""
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "limit and offset must be integers")
    if limit < 1 or limit > 100:
        raise_err(ERR_INVALID_REQUEST, "limit must be in [1, 100]")
    if offset < 0:
        raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def sort_and_page(items, limit, offset):
    """Sort by created_at ASC (§2.3), never by id / insertion order. Return
    (window, total_count)."""
    from db import parse_iso as _parse_iso
    ordered = sorted(items, key=lambda e: (_parse_iso(e["created_at"]), e.get("_seq", 0)))
    total = len(ordered)
    window = ordered[offset: offset + limit]
    return window, total
