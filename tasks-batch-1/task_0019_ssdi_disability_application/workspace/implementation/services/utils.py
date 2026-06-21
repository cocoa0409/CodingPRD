"""Shared helpers: parsing, pagination, USPS state list."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import APIError, ERR_INVALID_REQUEST, invalid_request


USPS_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}


def parse_iso8601(s: str, field_name: str = "datetime") -> datetime:
    if not isinstance(s, str):
        raise invalid_request(f"{field_name} must be an ISO 8601 string")
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise invalid_request(f"{field_name} is not a valid ISO 8601 datetime: {s}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def parse_pagination(args) -> tuple[int, int]:
    """Parse limit/offset from query args with defaults limit=10, min 1, max 100, offset=0."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise invalid_request("limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise invalid_request("offset must be >= 0")
    return limit, offset


def sort_by_created_at(items: list) -> list:
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    items = sort_by_created_at(items)
    total = len(items)
    return items[offset : offset + limit], total


def require_body() -> dict:
    from flask import request

    body = request.get_json(silent=True)
    if body is None:
        # Allow empty-body POSTs that take no input.
        if request.content_length in (None, 0):
            return {}
        raise invalid_request("request body must be JSON")
    if not isinstance(body, dict):
        raise invalid_request("request body must be a JSON object")
    return body


def require_field(body: dict, field: str):
    if field not in body or body[field] is None:
        raise invalid_request(f"missing required field: {field}")
    return body[field]


def require_str(body: dict, field: str) -> str:
    v = require_field(body, field)
    if not isinstance(v, str):
        raise invalid_request(f"field {field} must be a string")
    return v


def require_int(body: dict, field: str) -> int:
    v = require_field(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"field {field} must be an integer")
    return v


def opt_int(body: dict, field: str, default=0) -> int:
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"field {field} must be an integer")
    return v


def opt_str(body: dict, field: str, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise invalid_request(f"field {field} must be a string")
    return v


def round_half_up(value) -> int:
    """Round a Decimal/float to nearest integer, half up."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def add_months(dt: datetime, months: int) -> datetime:
    """Shift dt forward (or backward) by an integer number of months,
    preserving day-of-month where possible and clamping to month-end otherwise.
    """
    y = dt.year
    m = dt.month + months
    # Normalize month to 1..12
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    # Clamp day to last day of target month
    import calendar

    last_day = calendar.monthrange(y, m)[1]
    d = min(dt.day, last_day)
    return dt.replace(year=y, month=m, day=d)


def first_day_of_month(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def months_between(start: datetime, end: datetime) -> int:
    """Whole months between two dates (end - start). Negative if end < start."""
    return (end.year - start.year) * 12 + (end.month - start.month)


def years_between(start: datetime, end: datetime) -> int:
    """Whole completed years between start and end (used for age calc).
    Subtracts 1 if end's month/day has not yet reached start's month/day.
    """
    years = end.year - start.year
    if (end.month, end.day) < (start.month, start.day):
        years -= 1
    return years


def is_age_at_least(birth: datetime, now: datetime, years: int) -> bool:
    return years_between(birth, now) >= years
