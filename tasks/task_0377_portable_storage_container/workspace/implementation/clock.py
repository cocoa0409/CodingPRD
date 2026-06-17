"""Single server-held logical clock (PRD §2.8).

All time-dependent arithmetic — created_at stamping, due_date derivation, and
days_overdue computation — reads from this one logical clock expressed as a UTC
instant. The clock starts at process boot wall-clock and can be set via
POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._now = datetime.now(timezone.utc)

    def now(self):
        """Return current logical UTC instant (aware datetime)."""
        return self._now

    def set(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt.astimezone(timezone.utc)

    def iso(self):
        """ISO 8601 UTC with exactly three fractional digits, 'Z' suffix."""
        return fmt_iso(self._now)


def fmt_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    # millisecond precision, three fractional digits, Z suffix
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(s, str) or not s:
        raise ValueError("bad datetime")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
