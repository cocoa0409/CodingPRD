"""Shared helpers: ids, timestamps, parsing, rounding, serialization."""
import re
import uuid
from datetime import datetime, date, timezone

from errors import validation


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{dt.microsecond // 1000:03d}Z"


def parse_datetime(value, field):
    """Parse an ISO 8601 datetime; returns tz-aware UTC datetime."""
    if not isinstance(value, str):
        raise validation(f"{field} must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise validation(f"{field} is not a parseable ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field):
    """Parse an ISO date (YYYY-MM-DD); returns datetime.date."""
    if not isinstance(value, str):
        raise validation(f"{field} must be an ISO date string")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise validation(f"{field} is not a parseable ISO date")


_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


def parse_period(value, field="period"):
    """Validate YYYY-MM shape; returns (year, month)."""
    if not isinstance(value, str) or not _PERIOD_RE.match(value):
        raise validation(f"{field} must match YYYY-MM")
    year = int(value[0:4])
    month = int(value[5:7])
    if month < 1 or month > 12:
        raise validation(f"{field} must match YYYY-MM with a valid month")
    return year, month


def period_bounds(period):
    """Return (start_date, end_date) covering [period-01, first day of next month)."""
    year, month = parse_period(period)
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end
