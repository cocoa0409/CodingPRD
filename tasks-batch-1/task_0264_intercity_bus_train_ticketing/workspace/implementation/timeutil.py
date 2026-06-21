"""Time / date helpers (ISO 8601 UTC with three fractional digits)."""
from datetime import datetime, timezone, date


def iso_now(dt):
    """Format a tz-aware datetime as ISO 8601 UTC with millisecond precision."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 UTC instant (accepts trailing Z or offset)."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse a 'YYYY-MM-DD' calendar date into a date object."""
    return datetime.strptime(s, "%Y-%m-%d").date()


def floor_days_between(target_date, clock_dt):
    """Whole-day calendar difference (target_date - clock_now_date), can be negative."""
    clock_date = clock_dt.astimezone(timezone.utc).date()
    return (target_date - clock_date).days
