"""Logical clock — server-managed 'now' that can be advanced by admin."""

from datetime import datetime, timezone


class LogicalClock:
    """Singleton-like logical clock. Defaults to real time but can be set."""

    def __init__(self):
        self._fixed_now = None

    def now(self) -> datetime:
        if self._fixed_now is not None:
            return self._fixed_now
        return datetime.now(timezone.utc)

    def advance_to(self, iso_timestamp: str) -> datetime:
        # Parse with timezone awareness; if missing TZ assume UTC
        s = iso_timestamp.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        self._fixed_now = dt
        return dt

    def now_iso(self) -> str:
        """Return logical-clock now as ISO 8601 UTC with three fractional digits."""
        n = self.now()
        # Format with milliseconds precision and trailing Z
        return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


clock = LogicalClock()
