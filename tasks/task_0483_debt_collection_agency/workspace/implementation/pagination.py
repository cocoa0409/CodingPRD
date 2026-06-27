"""List pagination & sorting (PRD 2.3). limit default 10, min 1, max 100; offset default 0.
Sorted by created_at ascending unless otherwise stated."""
from flask import request

from errors import ApiError, ERR_INVALID_REQUEST

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _parse_int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise ApiError(*ERR_INVALID_REQUEST, message="Query param '%s' must be an integer" % name)


def get_pagination():
    limit = _parse_int_param("limit", LIMIT_DEFAULT)
    offset = _parse_int_param("offset", OFFSET_DEFAULT)
    if limit < LIMIT_MIN:
        limit = LIMIT_MIN
    if limit > LIMIT_MAX:
        limit = LIMIT_MAX
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items):
    """Sort by created_at asc, then apply limit/offset. Returns (page, limit, offset, total)."""
    limit, offset = get_pagination()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
