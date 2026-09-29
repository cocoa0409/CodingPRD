"""Pure helpers: time formatting/parsing, whole-day arithmetic, exact rounding."""
import math
import re
from datetime import datetime, timedelta, timezone

SECONDS_PER_DAY = 86400

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits, e.g.
    2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def parse_datetime(value):
    """Parse an ISO 8601 UTC instant. Returns an aware UTC datetime or None when
    the value is not a well formed instant."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    if second == 60:
        return None
    try:
        base = datetime(year, month, day, hour, minute, second, micro,
                        tzinfo=timezone.utc)
    except ValueError:
        return None
    off = m.group(8)
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        body = off[1:].replace(":", "")
        oh, om = int(body[:2]), int(body[2:])
        if oh > 23 or om > 59:
            return None
        base = base - sign * timedelta(hours=oh, minutes=om)
    return base


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date. Returns the canonical string or None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return value.strip()


def date_of(dt):
    """The UTC calendar date of an instant, as YYYY-MM-DD."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def whole_days(start, end):
    """Whole complete 86,400-second days from start to end, partial days
    discarded."""
    if start is None or end is None:
        return None
    return int(math.floor((end - start).total_seconds() / SECONDS_PER_DAY))


def whole_years(start, end, days_per_year=365):
    """Whole complete years (365 * 86,400 seconds each) from start to end."""
    if start is None or end is None:
        return None
    span = days_per_year * SECONDS_PER_DAY
    return int(math.floor((end - start).total_seconds() / span))


def add_days(dt, days):
    return dt + timedelta(days=days)


def rhu(numerator, denominator):
    """Exact integer division of numerator/denominator rounded half up, i.e.
    ties away from zero. Operands are integers so no binary float is involved."""
    numerator = int(numerator)
    denominator = int(denominator)
    if denominator == 0:
        raise ZeroDivisionError("round_half_up with zero denominator")
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((-2 * numerator + denominator) // (2 * denominator))
