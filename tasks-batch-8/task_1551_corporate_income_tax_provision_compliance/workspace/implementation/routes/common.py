"""Shared helpers for route handlers: filter extraction and pagination."""
from flask import request

from errors import raise_error, ERR_NOT_FOUND


def get_or_404(table: dict, entity_id: str, what: str):
    rec = table.get(entity_id)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"{what} '{entity_id}' does not exist")
    return rec


def apply_filters(records, filters: dict):
    """Exact-match filters from query params; absent params filter nothing."""
    out = list(records)
    for param, field in filters.items():
        v = request.args.get(param)
        if v is not None:
            out = [r for r in out if str(r.get(field)) == v]
    return out


def paginate(records):
    """limit/offset per PRD §2.3: limit default 10, min 1, max 100; offset default 0.
    Out-of-range values are clamped; unparseable values fall back to defaults.
    Records arrive in store insertion order (created_at ascending)."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(100, limit))
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)
    total = len(records)
    page = records[offset:offset + limit]
    return page, total, limit, offset
