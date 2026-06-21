"""Pagination per PRD §2.3: limit (default 10, 1..100), offset (default 0)."""
from flask import request
from errors import err, ERR_INVALID_REQUEST

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _parse_int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err(ERR_INVALID_REQUEST, f"Query parameter '{name}' must be an integer")


def get_pagination():
    limit = _parse_int_param("limit", DEFAULT_LIMIT)
    offset = _parse_int_param("offset", DEFAULT_OFFSET)
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise err(ERR_INVALID_REQUEST, f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")
    if offset < 0:
        raise err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items already sorted; return the page slice."""
    return items[offset:offset + limit]
