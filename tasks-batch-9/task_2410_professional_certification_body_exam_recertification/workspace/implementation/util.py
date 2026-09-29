"""Shared primitives: timestamp handling, calendar arithmetic, decimal rounding.

PRD 2.4: timestamps are ISO 8601 UTC with exactly three fractional digits.
PRD 2.5: every non-integral quantity uses decimal arithmetic with ROUND_HALF_UP.
"""

import calendar
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

UTC = timezone.utc

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fmt_ts(dt):
    """Serialise an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_ts(value):
    """Parse an ISO 8601 instant. Returns None when the value is not parseable."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        if _DATE_ONLY.match(raw):
            return datetime(int(raw[0:4]), int(raw[5:7]), int(raw[8:10]), tzinfo=UTC)
        text = raw
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=int(minutes))


def add_months(dt, months):
    """Calendar-month advance, clamping the day to the target month's length."""
    months = int(months)
    total = (dt.year * 12) + (dt.month - 1) + months
    year = total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def whole_days_between(later, earlier):
    """Whole (floored) days elapsed from `earlier` to `later`."""
    return (later - earlier).days


def dec(value):
    """Coerce to Decimal without inheriting binary floating point noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places):
    q = Decimal(1).scaleb(-int(places))
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def num_out(value):
    """Serialise a Decimal/number for JSON output."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def decimal_places(value):
    exponent = dec(value).normalize().as_tuple().exponent
    if not isinstance(exponent, int):
        return 0
    return max(0, -exponent)
