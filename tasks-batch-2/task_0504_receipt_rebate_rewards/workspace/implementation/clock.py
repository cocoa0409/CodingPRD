"""Logical clock. Starts at 2026-01-01T00:00:00Z on every boot; never falls back
to wall-clock time."""
from datetime import datetime, timezone

# The default logical clock instant at server startup (PRD §2.10).
DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"


class Clock:
    def __init__(self):
        self.now = parse_iso(DEFAULT_CLOCK_ISO)

    def get(self):
        return self.now

    def set(self, dt):
        self.now = dt


def parse_iso(s):
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime (UTC).

    Accepts a trailing 'Z' or an explicit offset. Returns None on failure.
    """
    if not isinstance(s, str):
        return None
    text = s.strip()
    if not text:
        return None
    # Normalize trailing Z to +00:00 for fromisoformat.
    candidate = text
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_iso(dt):
    """Format a timezone-aware datetime as ISO 8601 UTC with three fractional
    digits and a trailing Z (PRD §2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
