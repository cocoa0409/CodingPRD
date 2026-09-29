"""The logical clock (PRD section 2.5).

The server never reads host wall-clock time for any domain value. The startup
value is exactly 2026-08-01T00:00:00Z.
"""
from datetime import datetime, timezone

STARTUP = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = STARTUP

    def now(self):
        return self._now

    def set(self, instant):
        self._now = instant
        return self._now


clock = LogicalClock()


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso(clock.now())


def parse_iso(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    text = raw
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
