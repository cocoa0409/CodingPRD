"""Server logical clock and timestamp helpers.

The clock is in-memory only and is driven by the test harness through the
/_clock endpoints (PRD §2.10). It starts at real wall time on boot and never
persists across process restarts.
"""

from datetime import datetime, timezone


class Clock:
    def __init__(self):
        # Server "now" used for issue_date stamping, contract_year, and
        # date-of-death checks. Starts at real wall time; the test harness
        # overrides it via POST /_clock/set_current_utc.
        self._now = datetime.now(timezone.utc)

    def now(self):
        return self._now

    def set_now(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt.astimezone(timezone.utc)

    def iso_now(self):
        return iso8601(self._now)


def iso8601(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso8601(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime, or return None."""
    if not isinstance(value, str) or not value:
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
