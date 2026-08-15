"""ISO-8601 parsing/formatting and calendar arithmetic.

All timestamps on the wire are ISO 8601 UTC with exactly three fractional
digits, e.g. 2026-08-01T00:00:00.000Z.
"""
import re
from datetime import datetime, timedelta, timezone, date

_ISO_RE = re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})"
    r"(?:[T ](?P<h>\d{2}):(?P<mi>\d{2})(?::(?P<s>\d{2})(?:\.(?P<f>\d{1,9}))?)?)?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not an ISO-8601 string")
    s = value.strip()
    m = _ISO_RE.match(s)
    if not m:
        raise ValueError("not an ISO-8601 string")
    try:
        year = int(m.group("y"))
        month = int(m.group("mo"))
        day = int(m.group("d"))
        hour = int(m.group("h") or 0)
        minute = int(m.group("mi") or 0)
        second = int(m.group("s") or 0)
        frac = m.group("f") or ""
        micro = int((frac + "000000")[:6]) if frac else 0
        tzs = m.group("tz")
        if tzs is None or tzs in ("Z", "z"):
            tz = timezone.utc
        else:
            sign = 1 if tzs[0] == "+" else -1
            digits = tzs[1:].replace(":", "")
            tz = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:4])))
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=tz)
    except ValueError:
        raise ValueError("not an ISO-8601 string")
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _total_us(delta):
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def floor_days(delta):
    """Whole days in delta, floored (fractional days discarded downward)."""
    return _total_us(delta) // (86400 * 1_000_000)


def trunc_days(delta):
    """Whole days in delta, truncated toward zero."""
    us = _total_us(delta)
    q = abs(us) // (86400 * 1_000_000)
    return q if us >= 0 else -q


def add_years(dt, years):
    """Same calendar date N years later; Feb 29 maps to Feb 28 in non-leap years."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, day=28)


HOLIDAYS = {date(2026, 1, 1), date(2026, 7, 4), date(2026, 12, 25)}


def business_days_between(start_dt, end_dt):
    """Count calendar dates strictly after date(start_dt) and on-or-before
    date(end_dt) that fall Monday..Friday and are not in HOLIDAYS.
    The intake date itself is never counted."""
    d0 = start_dt.date()
    d1 = end_dt.date()
    if d1 <= d0:
        return 0
    count = 0
    d = d0 + timedelta(days=1)
    while d <= d1:
        if d.weekday() < 5 and d not in HOLIDAYS:
            count += 1
        d += timedelta(days=1)
    return count
