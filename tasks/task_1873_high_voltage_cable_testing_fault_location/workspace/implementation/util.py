"""Time, decimal and rounding helpers. All rounding is round-half-up."""
import calendar
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING


def iso(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime; None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def dec(value):
    """Coerce a JSON number to Decimal; None when not numeric (bool excluded)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    return None


def rhu(x, places):
    """Round half up to the given number of decimal places."""
    q = Decimal(1).scaleb(-places)
    return x.quantize(q, rounding=ROUND_HALF_UP)


def ceil_dec(x):
    return int(x.to_integral_value(rounding=ROUND_CEILING))


def _total_us(delta):
    return delta.days * 86400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def whole_minutes(a, b):
    """Whole minutes between two datetimes (floor); b must be >= a."""
    return int(_total_us(b - a) // 60_000_000)


def ceil_minutes(delta):
    """Ceiling of a timedelta expressed in minutes; negative clamps to 0."""
    us = _total_us(delta)
    if us <= 0:
        return 0
    return int(-(-us // 60_000_000))


def hours_between(a, b):
    """Exact Decimal hours between two datetimes."""
    return Decimal(_total_us(b - a)) / Decimal(3_600_000_000)


def minus_months(dt, months):
    total = (dt.year * 12 + (dt.month - 1)) - months
    year = total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)
