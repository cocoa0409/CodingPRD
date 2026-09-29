"""Server-held forward-only logical clock (in-memory only)."""
from datetime import datetime, timezone, timedelta

START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": START}


def now():
    return _state["now"]


def set_now(value):
    _state["now"] = value


def reset():
    _state["now"] = START


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def diff_days(later, earlier):
    """Floor-truncated whole-day difference (later - earlier)."""
    delta = later - earlier
    return delta.days if delta.total_seconds() >= 0 else -((-delta).days + (1 if (-delta).seconds or (-delta).microseconds else 0))


def floor_days(later, earlier):
    """Whole days from earlier to later, floor-truncated; negative when later < earlier."""
    seconds = (later - earlier).total_seconds()
    return int(seconds // 86400)


def add_calendar_years(dt, years):
    """Advance by whole calendar years, same month/day; 29 Feb -> 1 Mar."""
    y = dt.year + int(years)
    if dt.month == 2 and dt.day == 29:
        try:
            return dt.replace(year=y, month=2, day=29)
        except ValueError:
            return dt.replace(year=y, month=3, day=1)
    return dt.replace(year=y)


def fmt_wall():
    """Envelope timestamp: real wall-clock UTC, three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"
