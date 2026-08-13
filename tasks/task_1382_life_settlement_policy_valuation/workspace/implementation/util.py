"""Date/time and rounding helpers.

All monetary rounding is round-half-up to integer cents. The logical clock
yields whole-second timestamps in practice; fractional milliseconds are only
emitted when the clock was set with sub-second precision.
"""

import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def fmt_dt(dt):
    """ISO 8601 UTC. Milliseconds are emitted only when nonzero."""
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    if ms:
        base += ".%03d" % ms
    return base + "Z"


def fmt_dt_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits (meta timestamps)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def parse_dt(s):
    """Parse an ISO 8601 datetime; naive values are treated as UTC."""
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        raise ValueError("not a date string")
    return date.fromisoformat(s.strip())


def add_months(d, months):
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def days_between(a, b):
    """Whole/fractional days between two datetimes (or dates coerced)."""
    if isinstance(a, date) and not isinstance(a, datetime):
        a = datetime(a.year, a.month, a.day, tzinfo=timezone.utc)
    if isinstance(b, date) and not isinstance(b, datetime):
        b = datetime(b.year, b.month, b.day, tzinfo=timezone.utc)
    return (b - a).total_seconds() / 86400.0


def rhu(x):
    """Round-half-up to the nearest integer (accepts float/int/Decimal/str)."""
    if isinstance(x, float):
        x = repr(x)
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_div(numer, denom):
    """Exact rational round-half-up: rhu(numer / denom) for int inputs."""
    return int(
        (Decimal(int(numer)) / Decimal(int(denom))).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
