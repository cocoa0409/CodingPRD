"""Logical clock.

The server keeps a logical clock that supplies every system-stamped timestamp:
a custody event's occurred_at, a certificate's cremated_at, and the basis for
all scheduling comparisons (PRD section 2.9). At startup the clock reads exactly
2026-01-01T00:00:00Z and never falls back to wall-clock time.
"""

from datetime import datetime, timezone

DEFAULT_CLOCK = "2026-01-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._current = parse_iso8601(DEFAULT_CLOCK)

    def set(self, iso_str):
        self._current = parse_iso8601(iso_str)

    def now_dt(self):
        return self._current

    def now_iso(self):
        return format_iso8601(self._current)


def parse_iso8601(s):
    """Parse an ISO 8601 string (accepting a trailing Z) into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    text = s.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso8601(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits and a Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
