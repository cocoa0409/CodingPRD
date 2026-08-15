"""Date/time parsing and comparison utilities.

- Datetimes: ISO 8601 UTC. Compared at minute granularity for windows.
- Deadline comparisons: day granularity (datetime truncated to its UTC date first),
  inclusive upper bounds (PRD §2.5, §2.7).
"""

import re
from datetime import datetime, date, timezone


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_datetime(value):
    """Parse an ISO 8601 datetime string to an aware datetime in UTC, or None."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    try:
        year, mo, day, hh, mm, ss = (int(m.group(i)) for i in range(1, 7))
        frac = m.group(7)
        micro = 0
        if frac:
            digits = frac[1:]
            micro = int((digits + "000000")[:6])
        tz = m.group(8)
        if tz is None or tz == "Z":
            tzinfo = timezone.utc
        else:
            sign = 1 if tz[0] == "+" else -1
            tzd = tz[1:].replace(":", "")
            oh, om = int(tzd[:2]), int(tzd[2:4])
            from datetime import timedelta

            tzinfo = timezone(sign * timedelta(hours=oh, minutes=om))
        dt = datetime(year, mo, day, hh, mm, ss, micro, tzinfo=tzinfo)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def parse_date(value):
    """Parse an ISO 8601 date string (YYYY-MM-DD) to a date, or None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def to_utc_date(value):
    """Truncate a datetime (or datetime-string) to its UTC calendar date.

    Accepts datetime objects or ISO strings; returns a `date`.
    """
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).date()
    if isinstance(value, str):
        d = parse_date(value)
        if d is not None and "T" not in value:
            return d
        dt = parse_datetime(value)
        if dt is not None:
            return dt.date()
        return d
    if isinstance(value, date):
        return value
    return None


def format_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_logical(store):
    """The logical campaign clock value (aware datetime)."""
    return store.clock_now
