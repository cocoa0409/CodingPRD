"""Server logical clock (PRD §2.11).

Time is a server-controlled logical clock. On startup it reads exactly
2026-01-01T00:00:00Z and never falls back to wall-clock time. The clock drives
pack_date, lot expiry at run start, and elapsed time for throughput.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

# Module-level state. Reset on every fresh process (per-test-server isolation).
_current = DEFAULT_CLOCK


def now():
    """Return the current logical clock instant (aware UTC datetime)."""
    return _current


def set_now(dt):
    global _current
    _current = dt
    return _current


def reset():
    global _current
    _current = DEFAULT_CLOCK


def parse_iso8601(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or return None.

    Accepts a trailing 'Z' (Python 3.9 fromisoformat does not). Naive inputs
    are treated as UTC.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso_millis(dt):
    """Format an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    # microseconds -> milliseconds, truncate (datetime stores micros)
    millis = dt.microsecond // 1000
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.{:03d}Z".format(
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, millis
    )
