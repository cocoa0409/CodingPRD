"""Shared utilities: decimal rounding, datetime parsing/formatting, month arithmetic."""
import calendar
from datetime import datetime, timezone

from decimal import Decimal, ROUND_HALF_UP


def D(value):
    """Coerce a JSON number (int/float/str) to Decimal via str() to avoid float artifacts."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    """Round half-up to the given number of decimal places; returns Decimal."""
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def wall_now():
    """Wall-clock UTC now (used for created_at/updated_at/meta timestamps)."""
    return datetime.now(timezone.utc)


def iso_millis(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime string. Accepts trailing Z or offsets.

    Returns an aware UTC datetime. Raises ValueError on bad input.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    """Shift dt forward by `months` calendar months, clamping the day-of-month
    to the last day of the target month when needed."""
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


def num_out(value):
    """Serialize a Decimal/numeric as a plain JSON number."""
    if isinstance(value, Decimal):
        return float(value)
    return value
