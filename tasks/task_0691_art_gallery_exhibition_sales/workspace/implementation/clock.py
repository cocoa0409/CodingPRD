"""Logical clock helpers (PRD §2.7). Default 2026-04-01T00:00:00Z until set."""
from datetime import datetime, timezone

DEFAULT_CLOCK = "2026-04-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO 8601 UTC instant. Returns a timezone-aware datetime or
    raises ValueError. Accepts trailing 'Z' or explicit offset."""
    if not isinstance(value, str) or not value:
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g.
    2026-04-01T00:00:00.000Z (PRD §2.4 timestamps)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def format_iso_clock(dt):
    """Canonical clock_utc / event-instant rendering: no fractional digits,
    trailing Z (matches the 2026-04-01T00:00:00Z default form)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
