"""List pagination + sorting (PRD §2.3).

limit defaults to 10 (min 1, max 100); offset defaults to 0. List endpoints
return resources sorted by creation timestamp ascending.
"""
from flask import request

from errors import err, ERR_INVALID_REQUEST

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _parse_int_param(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, f"Query parameter {name} must be an integer")


def get_limit_offset():
    limit = _parse_int_param("limit", DEFAULT_LIMIT)
    offset = _parse_int_param("offset", DEFAULT_OFFSET)
    if limit < MIN_LIMIT:
        limit = MIN_LIMIT
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(records, serializer):
    """Sort by created-order ascending, apply limit/offset, serialize.

    Returns (items, limit, offset, total_count).
    """
    limit, offset = get_limit_offset()
    ordered = sorted(records, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    items = [serializer(r) for r in window]
    return items, limit, offset, total
