"""Pagination helpers."""
from flask import request

from errors import raise_api

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = DEFAULT_LIMIT
        if limit < MIN_LIMIT:
            limit = MIN_LIMIT
        if limit > MAX_LIMIT:
            limit = MAX_LIMIT
    if offset_raw is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            offset = DEFAULT_OFFSET
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    sliced = items[offset:offset + limit]
    return sliced, total
