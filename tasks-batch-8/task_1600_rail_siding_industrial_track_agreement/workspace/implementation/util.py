"""Parsing, validation, rounding, and pagination helpers."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import LOGICAL_CLOCK
from errors import ApiError


# ---------------------------------------------------------------------------
# Dates and times
# ---------------------------------------------------------------------------

def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware datetime (UTC assumed)."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_ymd(value):
    """Parse a YYYY-MM-DD date string into a date."""
    if not isinstance(value, str):
        raise ValueError("not a date string")
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def logical_now_dt():
    """Current logical clock as an aware datetime."""
    return parse_dt(LOGICAL_CLOCK["current"])


def logical_today():
    """UTC calendar date of the logical clock."""
    return logical_now_dt().date()


def format_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with the Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def date_to_str(d):
    return d.isoformat()


def add_months(d, months):
    """Add N months to a date, preserving day-of-month when possible."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = d.day
    # Clamp day-of-month to the target month's last day.
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1


def add_days(d, days):
    return d + timedelta(days=days)


def whole_days_between(a, b):
    """Whole days from date a to date b (b - a in days)."""
    return (b - a).days


def day_of_week_code(d):
    """MON/TUE/.../SUN for a date."""
    return ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"][d.weekday()]


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------

def round_half_up_int(value):
    """Round a Decimal to the nearest integer, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round a Decimal to 2 decimal places, half-up."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Request body helpers — all raise ERR_INVALID_REQUEST (400) on bad shape
# ---------------------------------------------------------------------------

def body():
    """Return the JSON request body as a dict ({} when absent)."""
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be valid JSON")
        if not isinstance(data, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
        return data
    return {}


def required(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    return data[field]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def as_int(v, field):
    if not _is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an integer")
    return v


def as_str(v, field):
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a string")
    return v


def as_num(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a number")
    return v


def as_enum(v, field, choices):
    if v not in choices:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be one of {sorted(choices)}"
        )
    return v


def as_list(v, field):
    if not isinstance(v, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an array")
    return v


def as_iso_dt(v, field):
    as_str(v, field)
    try:
        parse_dt(v)
    except Exception:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO 8601 timestamp"
        )
    return v


def as_iso_date(v, field):
    as_str(v, field)
    try:
        parse_ymd(v)
    except Exception:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO date (YYYY-MM-DD)"
        )
    return v


def as_non_negative_int(v, field):
    v = as_int(v, field)
    if v < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be >= 0")
    return v


def as_positive_int(v, field):
    v = as_int(v, field)
    if v <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be > 0")
    return v


def as_pct(v, field):
    v = as_num(v, field)
    if v < 0 or v > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be between 0 and 100")
    return v


def pagination_args():
    """limit/offset query parameters with scaffold defaults (10 / 0, max 100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset
