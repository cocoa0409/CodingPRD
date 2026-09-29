"""Date / datetime helpers.  All instants are UTC; the service never reads
real wall-clock time (PRD 2.4)."""
from datetime import datetime, date, timedelta, timezone

UTC = timezone.utc


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_date(value):
    """Strict ISO 8601 calendar date.  Returns None when unparsable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        return None
    try:
        return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
    except (ValueError, TypeError):
        return None


def parse_dt(value):
    """ISO 8601 UTC instant.  Accepts a trailing Z, an explicit offset or a
    naive instant (interpreted as UTC).  Returns None when unparsable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_hhmm(value):
    """'HH:MM' clock time.  Returns (hour, minute) or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if len(s) != 5 or s[2] != ":":
        return None
    try:
        h = int(s[0:2])
        m = int(s[3:5])
    except (ValueError, TypeError):
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return (h, m)


def combine(d, hhmm):
    h, m = hhmm
    return datetime(d.year, d.month, d.day, h, m, 0, tzinfo=UTC)


def add_days(d, n):
    return d + timedelta(days=n)
