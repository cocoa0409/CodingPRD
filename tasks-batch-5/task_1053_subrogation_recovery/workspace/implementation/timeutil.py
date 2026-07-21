"""Datetime helpers. All instants are ISO 8601 UTC."""
from datetime import datetime, timezone, timedelta


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("datetime must be a string")
    t = s.strip()
    if t == "":
        raise ValueError("empty datetime")
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_wall():
    return datetime.now(timezone.utc)


def days(n):
    return timedelta(days=n)
