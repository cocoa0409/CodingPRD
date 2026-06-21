"""List filtering, sorting, and pagination (PRD 2.3).

Default sort: created_at ascending (ties broken by creation sequence). Pagination
params limit (default 10, min 1, max 100) and offset (default 0). Out-of-range
limit/offset values are rejected as malformed requests.
"""
from flask import request

from errors import err

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _parse_int_param(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "Query parameter %r must be an integer" % name)


def pagination_params():
    limit = _parse_int_param("limit", LIMIT_DEFAULT)
    offset = _parse_int_param("offset", OFFSET_DEFAULT)
    if limit < LIMIT_MIN or limit > LIMIT_MAX:
        raise err("ERR_INVALID_REQUEST", "limit must be between %d and %d" % (LIMIT_MIN, LIMIT_MAX))
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(records, serializer):
    """Sort by created_at asc (then sequence), paginate, and serialize.

    Returns (items, limit, offset, total_count).
    """
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset : offset + limit]
    items = [serializer(r) for r in window]
    return items, limit, offset, total
