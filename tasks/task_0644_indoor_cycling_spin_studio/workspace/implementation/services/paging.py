"""Pagination parsing & application (PRD §2.3, scaffold pagination_defaults).

limit: default 10, min 1, max 100. offset: default 0, min 0. Out-of-bounds ->
ERR_VALIDATION. Default sort: created_at ASC (PRD §2.3)."""
from flask import request

from errors import err, ERR_VALIDATION

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
MIN_OFFSET = 0


def _parse_int_param(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err(ERR_VALIDATION, "Query param '%s' must be an integer" % name)


def get_pagination():
    limit = _parse_int_param("limit", DEFAULT_LIMIT)
    offset = _parse_int_param("offset", DEFAULT_OFFSET)
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise err(ERR_VALIDATION, "limit must be between %d and %d" % (MIN_LIMIT, MAX_LIMIT))
    if offset < MIN_OFFSET:
        raise err(ERR_VALIDATION, "offset must be >= %d" % MIN_OFFSET)
    return limit, offset


def sort_default(records):
    """Sort by created_at ASC, internal seq as a stable tie-break (PRD §2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def apply_page(records, limit, offset):
    total = len(records)
    page = records[offset:offset + limit]
    return page, total
