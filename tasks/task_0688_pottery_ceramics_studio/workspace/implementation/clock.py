"""Logical clock (PRD §2.4, §3.12).

At startup the clock reads exactly 2026-04-01T00:00:00Z and stays there until
explicitly set; it NEVER falls back to wall-clock time. All temporal comparisons
in the system read this logical clock.

Timestamps are emitted as ISO 8601 UTC with three fractional digits (PRD §2.4).
"""

from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-04-01T00:00:00Z"


def _parse_iso(s):
    """Parse an ISO 8601 UTC instant. Accepts trailing 'Z' or +00:00.

    Returns a timezone-aware datetime in UTC. Raises ValueError on bad input.
    """
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    raw = s.strip()
    txt = raw
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso(dt):
    """Format a UTC datetime as ISO 8601 with three fractional digits + 'Z'."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Clock:
    def __init__(self):
        self._now = _parse_iso(DEFAULT_CLOCK_ISO)

    def now(self):
        """Current logical-clock datetime (UTC, tz-aware)."""
        return self._now

    def now_iso(self):
        """Current logical clock as ISO string with millis."""
        return _format_iso(self._now)

    def set_from_iso(self, iso_str):
        self._now = _parse_iso(iso_str)
        return self._now


# Module-level singleton, recreated on every process boot (fresh state).
clock = Clock()


def parse_iso(s):
    return _parse_iso(s)


def format_iso(dt):
    return _format_iso(dt)
