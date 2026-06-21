"""Logical UTC clock (PRD §2.9).

Time-sensitive behavior reads from this logical clock. The administrative
endpoint POST /v1/_clock/set overrides it; otherwise it follows wall-clock UTC.
All state is module-level and wiped on every fresh process boot.
"""
from datetime import datetime, timezone

# When set via /v1/_clock/set, this holds the logical "now". None => wall clock.
_override = None


def reset():
    global _override
    _override = None


def set_clock(dt):
    """dt is a timezone-aware datetime (UTC)."""
    global _override
    _override = dt


def now():
    """Return the current logical UTC datetime (timezone-aware)."""
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def format_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z.

    PRD §2.4: created_at/updated_at are ISO 8601 UTC with three fractional digits.
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    # microseconds -> milliseconds (3 digits), truncate
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".{:03d}Z".format(millis)


def now_iso():
    return format_iso(now())


def parse_iso(value):
    """Parse an ISO 8601 datetime string into a timezone-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive input is treated as UTC.
    Raises ValueError on malformed input.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
