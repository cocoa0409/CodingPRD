"""List pagination + sorting (PRD §2.3).

limit defaults to 10, range [1, 100]; offset defaults to 0. Results are sorted
by created_at ascending (we use the monotonic _seq, which is consistent with
created_at order and breaks ms-resolution ties deterministically).
"""
from flask import request

from errors import err

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
        raise err("ERR_INVALID_REQUEST", "query param %s must be an integer" % name)


def get_limit_offset():
    limit = _parse_int_param("limit", LIMIT_DEFAULT)
    offset = _parse_int_param("offset", OFFSET_DEFAULT)
    if limit < LIMIT_MIN or limit > LIMIT_MAX:
        raise err(
            "ERR_INVALID_REQUEST",
            "limit must be between %s and %s" % (LIMIT_MIN, LIMIT_MAX),
        )
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(records):
    """Sort by created_at ASC, apply limit/offset. Returns (page, limit, offset, total)."""
    limit, offset = get_limit_offset()
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return page, limit, offset, total
