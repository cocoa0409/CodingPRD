"""Shared list helpers: filtering, sorting, pagination (PRD §2.3, §2.4)."""
from flask import request

from errors import err, ERR_VALIDATION
from common import public

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination():
    """limit default 10 (1..100), offset default 0 (PRD §2.3)."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_v = DEFAULT_LIMIT
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            err(ERR_VALIDATION, "limit must be an integer")
        if limit_v < MIN_LIMIT or limit_v > MAX_LIMIT:
            err(ERR_VALIDATION, f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")
    if offset is None:
        offset_v = DEFAULT_OFFSET
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            err(ERR_VALIDATION, "offset must be an integer")
        if offset_v < 0:
            err(ERR_VALIDATION, "offset must be >= 0")
    return limit_v, offset_v


def filter_sort_paginate(collection, filters):
    """Apply equality filters, sort by created_at asc, paginate.

    filters: dict of {field_name: query_param_value} where None values are
    skipped. Sorting uses the internal _seq for a stable created_at ascending
    order (PRD §2.3).
    """
    items = list(collection.values())
    for field, value in filters.items():
        if value is not None:
            items = [r for r in items if str(r.get(field)) == str(value)]
    items.sort(key=lambda r: r.get("_seq", 0))
    total_count = len(items)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return [public(r) for r in page], limit, offset, total_count
