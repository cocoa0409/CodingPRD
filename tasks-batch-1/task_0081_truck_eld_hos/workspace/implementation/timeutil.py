"""ISO 8601 UTC helpers and home-terminal day partitioning (PRD §2.8)."""
import re
from datetime import datetime, timezone, timedelta

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def iso_now_str(dt):
    """Format a UTC datetime as ISO 8601 with exactly three fractional digits, Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_iso(s):
    """Parse an ISO 8601 UTC instant. Returns a timezone-aware UTC datetime or None on failure."""
    if not isinstance(s, str) or not s:
        return None
    txt = s.strip()
    # Normalize trailing Z to +00:00 for fromisoformat
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_date_str(s):
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def whole_minutes_between(start_dt, end_dt):
    """Whole minutes (floor) from start to end. Both UTC datetimes."""
    delta = (end_dt - start_dt).total_seconds()
    return int(delta // 60)


def home_terminal_date(event_dt, tz_offset_minutes):
    """Return the home-terminal calendar date (YYYY-MM-DD) for a UTC instant.

    The home terminal is tz_offset_minutes east of UTC; the local wall-clock date
    of the instant is the date that partitions daily logs (PRD §2.8).
    """
    local = event_dt.astimezone(timezone.utc) + timedelta(minutes=tz_offset_minutes)
    return local.strftime("%Y-%m-%d")


def date_to_ordinal(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").toordinal()
