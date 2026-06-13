"""List pagination per PRD §2.3: limit (default 10, 1..100), offset (default 0)."""
from flask import request

from errors import err

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _parse_int_param(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"Query param {name} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Query param {name} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", f"Query param {name} must be <= {maximum}")
    return v


def paginate(items):
    """Sort by created_at asc (tie-break on creation sequence), then page.

    Returns (page_items, meta_dict).
    """
    limit = _parse_int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _parse_int_param("offset", OFFSET_DEFAULT, 0, None)

    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
