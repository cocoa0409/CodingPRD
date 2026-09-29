"""The logical plan calendar (PRD 2.5).

The clock is positioned at 2026-08-01T00:00:00Z when the server starts and
never falls back to wall-clock time afterwards.
"""

from datetime import datetime, timezone

_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = _START

    def reset(self):
        self._now = _START

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt.astimezone(timezone.utc)

    def today(self):
        """The calendar date, YYYY-MM-DD, of the clock's current position."""
        return self._now.date()

    def today_iso(self):
        return self._now.date().isoformat()

    def current_utc(self):
        n = self._now
        return n.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (n.microsecond // 1000)


CLOCK = LogicalClock()


def parse_iso8601(raw):
    """Parse an ISO 8601 instant; returns an aware UTC datetime or None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def today():
    return CLOCK.today()


def today_iso():
    return CLOCK.today_iso()
