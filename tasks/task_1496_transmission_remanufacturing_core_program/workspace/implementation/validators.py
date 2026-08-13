"""Shared request-shape validation helpers (pipeline priority 3)."""

from datetime import datetime, timezone

from errors import ApiError, ERR_INVALID_REQUEST


def invalid(message):
    raise ApiError(ERR_INVALID_REQUEST, message, 400)


def get_json_body():
    from flask import request

    body = request.get_json(silent=True)
    if body is None:
        # Treat missing/invalid JSON as an empty object; required-field checks
        # below produce ERR_INVALID_REQUEST.
        body = {}
    if not isinstance(body, dict):
        invalid("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            invalid(f"Missing required field: {f}")


def check_string(value, name):
    if not isinstance(value, str) or value == "":
        invalid(f"Field {name} must be a non-empty string")


def check_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        invalid(f"Field {name} must be an integer")


def check_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid(f"Field {name} must be a number")


def check_positive(value, name):
    if value <= 0:
        invalid(f"Field {name} must be positive")


def check_enum(value, name, allowed):
    if value not in allowed:
        invalid(f"Field {name} must be one of {sorted(allowed)}")


def parse_iso8601(value, name):
    """Parse an ISO 8601 datetime string; raise ERR_INVALID_REQUEST if bad."""
    if not isinstance(value, str):
        invalid(f"Field {name} must be an ISO 8601 datetime string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        invalid(f"Field {name} must be a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_ts(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_limit_offset(args):
    """Parse pagination params with defaults: limit default 10 (min 1, max
    100), offset default 0. Out-of-range values are clamped."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
