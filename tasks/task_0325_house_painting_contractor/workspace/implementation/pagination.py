"""Pagination (PRD §2.3, SCAFFOLD §1.0).

limit default 10, min 1, max 100; offset default 0. Out-of-range or malformed
pagination params are treated as ERR_INVALID_REQUEST (422)? — The PRD only
defines defaults/bounds, so we clamp gracefully: invalid -> default/bounds.
"""
from flask import request

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _parse_int(raw, default):
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def get_pagination():
    limit = _parse_int(request.args.get("limit"), LIMIT_DEFAULT)
    offset = _parse_int(request.args.get("offset"), OFFSET_DEFAULT)
    if limit < LIMIT_MIN:
        limit = LIMIT_MIN
    if limit > LIMIT_MAX:
        limit = LIMIT_MAX
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
