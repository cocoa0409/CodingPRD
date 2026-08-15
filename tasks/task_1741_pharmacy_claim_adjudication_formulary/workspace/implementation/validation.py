from datetime import date

from flask import request

from errors import ApiError


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message, 400)


def body():
    """Request JSON body as a dict; anything else is treated as empty."""
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def parse_date(v):
    """Return a date for a valid ISO date string, else None."""
    if not isinstance(v, str):
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


def req_str(b, field):
    v = b.get(field)
    if not isinstance(v, str) or v == "":
        bad(f"Field '{field}' is required and must be a string")
    return v


def opt_str(b, field):
    v = b.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        bad(f"Field '{field}' must be a string")
    return v


def req_int(b, field, minimum=None):
    v = b.get(field)
    if not is_int(v):
        bad(f"Field '{field}' is required and must be an integer")
    if minimum is not None and v < minimum:
        bad(f"Field '{field}' must be >= {minimum}")
    return v


def opt_int(b, field, minimum=None, default=None):
    v = b.get(field)
    if v is None:
        return default
    if not is_int(v):
        bad(f"Field '{field}' must be an integer")
    if minimum is not None and v < minimum:
        bad(f"Field '{field}' must be >= {minimum}")
    return v


def req_bool(b, field):
    v = b.get(field)
    if not isinstance(v, bool):
        bad(f"Field '{field}' is required and must be a boolean")
    return v


def opt_bool(b, field, default=None):
    v = b.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        bad(f"Field '{field}' must be a boolean")
    return v


def req_enum(b, field, allowed):
    v = b.get(field)
    if v not in allowed:
        bad(f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def req_date(b, field):
    """Validate a required ISO date field; returns the normalized ISO string."""
    v = b.get(field)
    d = parse_date(v)
    if d is None:
        bad(f"Field '{field}' is required and must be a valid ISO date")
    return d.isoformat()


def opt_date(b, field):
    v = b.get(field)
    if v is None:
        return None
    d = parse_date(v)
    if d is None:
        bad(f"Field '{field}' must be a valid ISO date")
    return d.isoformat()


def pagination_params():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0 (min 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(records):
    """Sort by created_at asc, apply limit/offset, return (page, limit, offset, total)."""
    import db

    limit, offset = pagination_params()
    ordered = db.sorted_records(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [db.public(r) for r in page], limit, offset, total
