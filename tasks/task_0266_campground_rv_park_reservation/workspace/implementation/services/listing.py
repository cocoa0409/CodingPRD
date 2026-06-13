"""List/pagination helpers (PRD §2.3).

limit default 10, min 1, max 100; offset default 0. Sort by created_at ASC
(with insertion-seq tie-break to keep ordering stable when timestamps collide).
"""
from flask import request

import errors

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
    except (ValueError, TypeError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid %s parameter" % name)


def pagination():
    limit = _parse_int_param("limit", LIMIT_DEFAULT)
    offset = _parse_int_param("offset", OFFSET_DEFAULT)
    if limit < LIMIT_MIN:
        limit = LIMIT_MIN
    if limit > LIMIT_MAX:
        limit = LIMIT_MAX
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ASC (seq tie-break) and slice."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return page, total
