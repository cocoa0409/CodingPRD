"""Logical clock + datetime helpers (PRD §3.9, §2.4).

The clock defaults to 2026-05-01T00:00:00Z at server startup and is set
explicitly via POST /op/_clock/set_current_utc. All deadline/expiry/window
rules read this logical value, never wall-clock time.
"""
import datetime
import re

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"


def parse_iso(s):
    """Parse an ISO 8601 instant (Z or offset) into an aware UTC datetime."""
    if s is None:
        return None
    if isinstance(s, datetime.datetime):
        dt = s
    else:
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def parse_date(s):
    """Parse a YYYY-MM-DD date string into an aware UTC datetime at midnight."""
    if s is None:
        return None
    d = datetime.datetime.strptime(s, "%Y-%m-%d")
    return d.replace(tzinfo=datetime.timezone.utc)


def to_iso_z(dt):
    """Serialize an aware datetime to ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def now_iso():
    return to_iso_z(datetime.datetime.now(datetime.timezone.utc))


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_valid_date(s):
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return False
    try:
        datetime.datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def add_months(dt, months):
    """Add calendar months, preserving day-of-month, clamping to month end."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # clamp day to last day of target month
    if month == 12:
        next_first = datetime.datetime(year + 1, 1, 1, tzinfo=dt.tzinfo)
    else:
        next_first = datetime.datetime(year, month + 1, 1, tzinfo=dt.tzinfo)
    last_day = (next_first - datetime.timedelta(days=1)).day
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def add_years(dt, years):
    """Add calendar years, clamping Feb 29 -> Feb 28 where necessary."""
    return add_months(dt, years * 12)


def add_days(dt, days):
    return dt + datetime.timedelta(days=days)
