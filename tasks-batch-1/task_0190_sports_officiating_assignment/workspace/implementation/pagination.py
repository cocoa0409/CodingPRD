"""Pagination + list ordering (PRD §2.3, SCAFFOLD §1.0).

limit: default 10, min 1, max 100.
offset: default 0, min 0.
Values outside bounds / non-integer -> ERR_INVALID_REQUEST.
List results sorted by created_at ascending (stable by creation sequence).
"""
from flask import request

from errors import err, ERR_INVALID_REQUEST

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _parse_int(raw, name):
    try:
        if raw != str(int(raw)):
            raise ValueError()
        return int(raw)
    except (ValueError, TypeError):
        err(ERR_INVALID_REQUEST, "%s must be an integer" % name)


def get_pagination():
    args = request.args
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in args:
        limit = _parse_int(args.get("limit"), "limit")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            err(ERR_INVALID_REQUEST, "limit out of bounds")
    if "offset" in args:
        offset = _parse_int(args.get("offset"), "offset")
        if offset < OFFSET_MIN:
            err(ERR_INVALID_REQUEST, "offset out of bounds")
    return limit, offset


def sort_created(records):
    return sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


def paginate(records, limit, offset):
    """Sort by created_at asc, return (page_slice, total_count)."""
    ordered = sort_created(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
