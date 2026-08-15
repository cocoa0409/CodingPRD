"""Parsing, validation, rounding, date, and pagination helpers."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError


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


def add_months(d, months):
    """Add whole calendar months to a date, clamping the day to month length."""
    month_index = d.year * 12 + (d.month - 1) + months
    year = month_index // 12
    month = month_index % 12 + 1
    # days in target month
    if month == 12:
        next_first = datetime(year + 1, 1, 1).date()
    else:
        next_first = datetime(year, month + 1, 1).date()
    last_day = (next_first - timedelta(days=1)).day
    return datetime(year, month, min(d.day, last_day)).date()


def body():
    """Return the JSON request body as a dict ({} when absent)."""
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be valid JSON")
        if not isinstance(data, dict):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "Request body must be a JSON object"
            )
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


def as_bool(v, field):
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a boolean")
    return v


def as_enum(v, field, choices):
    if v not in choices:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be one of {sorted(choices)}"
        )
    return v


def as_date(v, field):
    as_str(v, field)
    try:
        return parse_ymd(v)
    except Exception:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO 8601 date"
        )


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


def round_half_up_decimal(value, quantum):
    """Round a Decimal to the given quantum, half-up, returning a Decimal."""
    return value.quantize(Decimal(quantum), rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    """Round a Decimal to the nearest integer, half-up, returning an int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num_str(x):
    """Render a numeric value as int when integral, else as a plain float.

    CE tallies are carried to 2 decimals; a value like 4.0 serializes as 4.0
    in JSON either way, but keeping integral values clean avoids float noise.
    """
    d = Decimal(str(x))
    if d == d.to_integral_value():
        return int(d)
    return float(d)
