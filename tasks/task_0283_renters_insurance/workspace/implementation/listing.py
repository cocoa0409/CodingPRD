"""List endpoint helpers: pagination + created_at-ascending ordering (PRD §2.3).

limit defaults to 10, min 1, max 100. offset defaults to 0, min 0.
Out-of-range / malformed pagination params -> ERR_INVALID_REQUEST.
Lists are ordered by created_at ascending (tie-broken by internal _seq).
"""
from flask import request

from errors import err
import store

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _parse_int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Query param {} must be an integer".format(name))
    if value < minimum:
        raise err("ERR_INVALID_REQUEST", "Query param {} below minimum".format(name))
    if maximum is not None and value > maximum:
        raise err("ERR_INVALID_REQUEST", "Query param {} above maximum".format(name))
    return value


def pagination_params():
    limit = _parse_int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _parse_int_param("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def paginate(records):
    """Sort by created_at ASC (tie-break _seq), apply limit/offset, serialize.
    Returns (items, limit, offset, total_count)."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    items = [store.serialize(r) for r in window]
    return items, limit, offset, total
