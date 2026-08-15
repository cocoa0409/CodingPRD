"""Time helpers: logical-clock formatting and strict ISO parsing.

Timestamps serialize as ISO 8601 UTC with exactly three fractional digits
(YYYY-MM-DDTHH:MM:SS.mmmZ). Calendar dates use strict YYYY-MM-DD.
"""
import re
from datetime import date, datetime, time, timedelta, timezone

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ]"
    r"(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?"
    r"(?:([Zz])|([+-])(\d{2}):?(\d{2}))?$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fmt_ts(dt):
    """datetime (aware UTC) -> 'YYYY-MM-DDTHH:MM:SS.mmmZ'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_timestamp(value):
    """Parse an ISO 8601 timestamp string into an aware UTC datetime.

    Returns None when the value is not a well-formed timestamp.
    Naive values (no offset) are treated as UTC.
    """
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    year, mon, day, hh, mm, ss = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7) or "0"
    micro = int(frac.ljust(6, "0")[:6])
    if m.group(8):  # Z
        offset = timezone.utc
    elif m.group(9):  # +/-HH:MM
        sign = 1 if m.group(9) == "+" else -1
        off = timedelta(hours=int(m.group(10)), minutes=int(m.group(11)))
        offset = timezone(sign * off)
    else:
        offset = timezone.utc
    try:
        dt = datetime(year, mon, day, hh, mm, ss, micro, tzinfo=offset)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Strictly parse a YYYY-MM-DD date string. Returns date or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def end_of_day_utc(d):
    """date -> datetime at 23:59:59.000Z of that day (date-only deadline rule)."""
    return datetime.combine(d, time(23, 59, 59), tzinfo=timezone.utc)


def start_of_day_utc(d):
    return datetime.combine(d, time(0, 0, 0), tzinfo=timezone.utc)
