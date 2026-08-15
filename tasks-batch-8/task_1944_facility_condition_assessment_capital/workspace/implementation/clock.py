"""Server logical clock (PRD section 2.8).

Starts at exactly 2026-08-01T00:00:00Z and never falls back to wall-clock
time before an explicit set. Governs current_calendar_year() for the
remaining-useful-life calculation and RefreshCycle.opened_at stamps.
"""

from datetime import datetime, timezone

from util import fmt_dt


class LogicalClock:
    def __init__(self):
        self._dt = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self._raw = "2026-08-01T00:00:00Z"

    def set(self, raw, dt):
        self._raw = raw
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._dt = dt.astimezone(timezone.utc)

    def year(self):
        return self._dt.year

    def now_iso(self):
        return fmt_dt(self._dt)

    @property
    def raw(self):
        return self._raw


logical_clock = LogicalClock()


def parse_iso(value):
    """Parse an ISO 8601 string into a datetime; None when unparseable."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None
