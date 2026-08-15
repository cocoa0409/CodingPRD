"""Shared helpers: decimal math, datetimes, validation primitives."""

import math
import re
from datetime import datetime, timezone

from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from errors import ApiError, ERR_INVALID_REQUEST

D = Decimal


def dec(value):
    """Convert a JSON number (int/float/str) to Decimal without float artifacts."""
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    return Decimal(str(value))


def round_half_up_int(x):
    """Round a Decimal to whole units, half up; returns int."""
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num_out(d):
    """Serialize a Decimal as int when integral, else float."""
    if not isinstance(d, Decimal):
        return d
    if d == d.to_integral_value():
        return int(d)
    return float(d)


DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def parse_dt(value, field):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be an ISO-8601 datetime string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' is not a valid ISO-8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
POOL_RE = re.compile(r"^(\d{4})-Q([1-4])$")


def check_month(value, field):
    if not isinstance(value, str) or not MONTH_RE.match(value):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be in YYYY-MM format")
    return value


def month_start(month_str):
    y, m = month_str.split("-")
    return datetime(int(y), int(m), 1, tzinfo=timezone.utc)


def quarter_of_month(month_str):
    y, m = month_str.split("-")
    q = (int(m) - 1) // 3 + 1
    return f"{y}-Q{q}"


def quarter_of_date(dt):
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{q}"


def quarter_end_exclusive(pool_period):
    """First instant after the last day of the quarter labelled by pool_period."""
    m = POOL_RE.match(pool_period)
    y, q = int(m.group(1)), int(m.group(2))
    next_month = q * 3 + 1
    if next_month > 12:
        return datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(y, next_month, 1, tzinfo=timezone.utc)


def month_in_year(month_str, year):
    return month_str.split("-")[0] == str(year)


def get_body(req):
    """Return the JSON request body as a dict; {} when absent."""
    body = req.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return body


def req_present(body, field):
    if field not in body or body[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field '{field}'")
    return body[field]


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be a non-empty string")
    return value


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be one of {sorted(allowed)}")
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be a boolean")
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be an integer")
    if isinstance(value, float):
        if not value.is_integer():
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be an integer")
        value = int(value)
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be a number")
    return value


def as_list(value, field):
    if not isinstance(value, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be an array")
    return value


def ceil_to_tenth(x):
    """Ceiling to the nearest 0.1."""
    return (x * Decimal(10)).to_integral_value(rounding=ROUND_CEILING) / Decimal(10)


def whole_days(delta):
    """Whole days of a timedelta, floored, never below zero."""
    return max(0, math.floor(delta.total_seconds() / 86400))
