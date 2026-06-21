"""Shared request-parsing, pagination, datetime, and money helpers."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err, ERR_INVALID_REQUEST

# Pagination defaults (SCAFFOLD response_envelope.pagination_defaults)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def get_json_body():
    """Parse the JSON request body, defaulting to {} for an empty body."""
    if request.data is None or len(request.data) == 0:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise err(ERR_INVALID_REQUEST, "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_enum(value, allowed, field_name):
    if value not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Invalid value for {field_name}")
    return value


def parse_pagination():
    """Read limit/offset query params, validate, return (limit, offset)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise err(ERR_INVALID_REQUEST, "limit out of range")

    if offset_raw is None:
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    """Slice an already-sorted list. Returns the page slice."""
    return items[offset:offset + limit]


def sort_by_created_at(items):
    """Sort ascending by created_at (PRD §2.3: oldest first).

    Ties (entities minted at the same simulated-clock millisecond) break by the
    monotonic creation-order sequence so list ordering is stable and matches
    insertion order rather than a random UUID.
    """
    return sorted(items, key=lambda o: (o.get("created_at", ""), o.get("_seq", 0)))


def parse_iso_dt(value):
    """Parse an ISO 8601 datetime string into a timezone-aware UTC datetime."""
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, "Invalid datetime value")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "Invalid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_test_date_start_utc(date_str):
    """Parse a YYYY-MM-DD date into midnight UTC at the start of that date."""
    if not isinstance(date_str, str):
        raise err(ERR_INVALID_REQUEST, "Invalid date value")
    try:
        d = datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "Invalid date (expected YYYY-MM-DD)")
    return d.replace(tzinfo=timezone.utc)


def round_half_up_cents(value):
    """Round a Decimal (or numeric) value half-up to a whole integer (cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def D(value):
    return Decimal(str(value))
