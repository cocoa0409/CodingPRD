"""Time parsing / formatting and rounding helpers.

All datetimes are timezone-aware UTC internally. They are serialized to
ISO 8601 UTC with exactly three fractional digits and a trailing 'Z'.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP


def parse_iso(s):
    """Parse an ISO-8601 string into an aware UTC datetime. Returns None on failure."""
    if s is None:
        return None
    if isinstance(s, datetime):
        dt = s
    elif isinstance(s, str):
        t = s.strip()
        if not t:
            return None
        if t.endswith('Z') or t.endswith('z'):
            t = t[:-1] + '+00:00'
        try:
            dt = datetime.fromisoformat(t)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """Format an aware datetime as ISO-8601 UTC with milliseconds and 'Z'."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f"{dt.microsecond // 1000:03d}Z"


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_years(dt, years):
    """Add calendar years, clamping Feb 29 -> Feb 28 when necessary."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, day=28)


def round_half_up(value, places=0):
    """Round a numeric/Decimal value half-up to the given number of decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def round_cents(value):
    """Round to whole integer cents, half-up."""
    return int(round_half_up(value, 0))
