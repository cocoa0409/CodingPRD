"""Logical clock. PRD §2.8: startup default 2026-04-01T00:00:00Z; never falls back
to wall-clock. Wherever the spec says "now", it means this logical clock."""
from datetime import datetime, timezone

# PRD §2.8 / scaffold: "At startup the clock reads exactly 2026-04-01T00:00:00Z"
DEFAULT_NOW_ISO = "2026-04-01T00:00:00Z"


class Clock:
    def __init__(self):
        self._now = _parse_iso(DEFAULT_NOW_ISO)

    def set(self, iso_str):
        self._now = _parse_iso(iso_str)
        return self.now_iso()

    def now(self):
        """Return the current logical instant as an aware datetime (UTC)."""
        return self._now

    def now_iso(self):
        """ISO 8601 UTC with three fractional digits (PRD §2.4)."""
        return iso_millis(self._now)


def _parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_millis(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    return _parse_iso(s)


clock = Clock()
