"""Field-level validation + pagination helpers.

These enforce the low-precedence well-formedness gate (PRD §2.9: required
fields present and well-typed, enum members valid -> ERR_INVALID_REQUEST 400).
The more specific stored-state business errors live in the service layer.
"""
import errors


def require(body, field):
    if field not in body or body[field] is None:
        raise errors.invalid_request("Missing required field: %s" % field)
    return body[field]


def _is_bool(v):
    return isinstance(v, bool)


def _is_int(v):
    # bool is a subclass of int in Python; exclude it.
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def as_string(v, field):
    if not isinstance(v, str):
        raise errors.invalid_request("Field %s must be a string." % field)
    return v


def as_int(v, field):
    if not _is_int(v):
        raise errors.invalid_request("Field %s must be an integer." % field)
    return v


def as_number(v, field):
    if not _is_number(v):
        raise errors.invalid_request("Field %s must be a number." % field)
    return v


def as_bool(v, field):
    if not _is_bool(v):
        raise errors.invalid_request("Field %s must be a boolean." % field)
    return v


def as_enum(v, field, members):
    if not isinstance(v, str) or v not in members:
        raise errors.invalid_request("Field %s must be one of %s." % (field, sorted(members)))
    return v


def as_datetime(v, field):
    """Datetimes are carried as ISO 8601 strings; parse to a comparable value."""
    if not isinstance(v, str):
        raise errors.invalid_request("Field %s must be an ISO 8601 datetime string." % field)
    parsed = parse_dt(v)
    if parsed is None:
        raise errors.invalid_request("Field %s is not a valid ISO 8601 datetime." % field)
    return v


def parse_dt(v):
    """Parse an ISO 8601 datetime string to an aware datetime, or None."""
    from datetime import datetime, timezone
    if not isinstance(v, str):
        return None
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------
def parse_pagination(args):
    limit = _parse_int_param(args, "limit", default=10)
    offset = _parse_int_param(args, "offset", default=0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_int_param(args, name, default):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise errors.invalid_request("Query parameter %s must be an integer." % name)


def paginate(rows, limit, offset):
    """Sort by created_at ASC (tie-break by creation sequence), then slice."""
    ordered = sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
