"""Shared helpers: request parsing, validation, serialization, pagination."""

from datetime import datetime, timezone

from flask import request

from errors import ApiError

# Fields that are internal bookkeeping and must never appear in API output.
_HIDDEN_FIELDS = {"_seq"}


def get_json_body():
    """Parse the JSON body; treat a missing/empty body as an empty object."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body, *names):
    for name in names:
        if name not in body or body[name] is None:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % name)


def serialize(record):
    """Strip internal fields for API output."""
    return {k: v for k, v in record.items() if k not in _HIDDEN_FIELDS}


def parse_iso(value, field_name="date"):
    """Parse an ISO 8601 datetime/date string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 string" % field_name)
    raw = value.strip()
    try:
        s = raw
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Try a bare date.
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "Invalid ISO 8601 value for %s" % field_name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_utc_date(dt):
    """Reduce an aware datetime to its UTC calendar date (for whole-day math)."""
    return dt.astimezone(timezone.utc).date()


def parse_date_field(value, field_name="date"):
    """Parse an input value to a UTC date for whole-day arithmetic."""
    return to_utc_date(parse_iso(value, field_name))


def pagination_params():
    """Read limit/offset query params with defaults/bounds (PRD §2.3)."""
    limit = _int_param("limit", default=10, minimum=1, maximum=100)
    offset = _int_param("offset", default=0, minimum=0, maximum=None)
    return limit, offset


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if val < minimum:
        val = minimum
    if maximum is not None and val > maximum:
        val = maximum
    return val


def paginate(items, limit, offset):
    """Apply offset/limit to an already-sorted list; return (page, total)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sort_by_creation(records):
    """Sort records by creation order ascending (PRD §2.3)."""
    return sorted(records, key=lambda r: r["_seq"])
