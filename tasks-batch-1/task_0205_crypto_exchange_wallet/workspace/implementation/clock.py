"""Logical ledger clock (§2.4). All time-dependent logic reads this clock."""
from datetime import datetime, timezone

_DAY_SECONDS = 24 * 3600


class Clock:
    def __init__(self):
        # Default to real wall-clock at boot; tests override via /_clock/set_current_utc.
        self._now = datetime.now(timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt.astimezone(timezone.utc)


def parse_iso8601(s):
    """Parse an ISO-8601 string, tolerating a trailing 'Z'."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(dt):
    """ISO-8601 UTC with three fractional digits and a trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
