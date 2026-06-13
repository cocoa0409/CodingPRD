"""Pagination parameter parsing (PRD §2.3): limit default 10, min 1, max 100; offset default 0."""
from flask import request

import errors

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse():
    """Return (limit, offset). Invalid values -> ERR_INVALID_REQUEST."""
    limit = _parse_int_param("limit", DEFAULT_LIMIT)
    offset = _parse_int_param("offset", DEFAULT_OFFSET)

    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise errors.invalid_request(
            "limit must be between %d and %d." % (MIN_LIMIT, MAX_LIMIT))
    if offset < 0:
        raise errors.invalid_request("offset must be >= 0.")
    return limit, offset


def _parse_int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise errors.invalid_request("%s must be an integer." % name)


def apply(items, limit, offset):
    """Sort by created_at ASC (via _created_dt), then slice."""
    ordered = sorted(items, key=lambda o: o["_created_dt"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
