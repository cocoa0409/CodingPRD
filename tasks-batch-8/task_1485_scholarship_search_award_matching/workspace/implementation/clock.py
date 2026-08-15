"""Logical clock. Startup default is exactly 2026-08-01T00:00:00Z; the system
never reads wall-clock time (PRD §2.6)."""

from datetime import datetime, timezone, timedelta

_DEFAULT_RAW = "2026-08-01T00:00:00Z"

_raw = _DEFAULT_RAW
_dt = None


def parse_iso(s):
    """Parse an ISO8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso3(dt):
    """Format an aware datetime as ISO8601 UTC with exactly 3 fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def now():
    return _dt


def now_iso():
    return iso3(_dt)


def now_echo():
    """Raw clock reading echoed by the clock-set endpoint."""
    return _raw


def set_clock(to_iso8601):
    global _raw, _dt
    _dt = parse_iso(to_iso8601)
    _raw = to_iso8601


def today():
    return _dt.date()


def days_from_now(n):
    return _dt + timedelta(days=n)


def parse_date(s):
    """Parse a YYYY-MM-DD date string. Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    return datetime.strptime(s, "%Y-%m-%d").date()


_dt = parse_iso(_DEFAULT_RAW)
