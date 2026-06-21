"""Pagination + filtered list helpers (PRD §2.3, §2.5)."""
from flask import request

from errors import err

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _parse_int_param(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Query param %s must be an integer" % name)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "Query param %s below minimum %s" % (name, minimum))
    if maximum is not None and val > maximum:
        raise err("ERR_INVALID_REQUEST", "Query param %s above maximum %s" % (name, maximum))
    return val


def get_limit_offset():
    limit = _parse_int_param("limit", DEFAULT_LIMIT, MIN_LIMIT, MAX_LIMIT)
    offset = _parse_int_param("offset", DEFAULT_OFFSET, 0, None)
    return limit, offset


def paginate(records):
    """Sort by creation order ascending, then slice by limit/offset."""
    limit, offset = get_limit_offset()
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
