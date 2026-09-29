"""Logical clock (PRD 2.4).

Every created_at / updated_at / certified_at / submitted_at / review_window_end /
decision_at / election_at / filed_at value, and every "logical clock date"
comparison, reads from this clock rather than the host wall clock.  At process
start it reads 2026-08-01T00:00:00Z and it only ever moves forward.
"""

from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def iso_of(dt):
    """ISO 8601 UTC with exactly three fractional digits, Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_iso(value):
    """Parse a client-supplied ISO 8601 instant.  Returns None when malformed."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = DEFAULT_CLOCK

    def reset(self):
        self._now = DEFAULT_CLOCK

    def now(self):
        return self._now

    def now_iso(self):
        return iso_of(self._now)

    def today(self):
        """The logical clock date."""
        return self._now.date()

    def set(self, dt):
        self._now = dt

    def plus_days_iso(self, days):
        return iso_of(self._now + timedelta(days=days))


clock = LogicalClock()
