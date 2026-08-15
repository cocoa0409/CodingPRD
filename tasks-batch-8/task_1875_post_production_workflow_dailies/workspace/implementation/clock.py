"""Facility logical clock (PRD §2.4).

All time-dependent behavior reads this single server-side logical clock,
never the real wall clock. Before the clock has ever been set it reads
exactly 2026-08-01T00:00:00Z and must not fall back to wall-clock time
under any circumstance.
"""

from datetime import datetime, timezone

_DEFAULT_ISO = "2026-08-01T00:00:00Z"


def _parse_iso(value):
    """Parse an ISO 8601 datetime string (accepts trailing 'Z')."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    def __init__(self):
        self._current = _parse_iso(_DEFAULT_ISO)

    def now(self):
        """Return the current logical time as an aware UTC datetime."""
        return self._current

    def set(self, iso_string):
        """Advance the clock to the supplied ISO 8601 instant."""
        self._current = _parse_iso(iso_string)
        return self._current


def format_iso(dt):
    """Format an aware UTC datetime as ISO 8601 with three fractional digits
    and a trailing 'Z' (PRD §2.8)."""
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


# Module-level singleton; fresh per process boot.
clock = LogicalClock()
