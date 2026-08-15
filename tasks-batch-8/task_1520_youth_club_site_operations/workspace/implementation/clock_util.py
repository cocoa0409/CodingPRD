"""The logical clock (PRD §2.4). Startup default is exactly 2026-08-01T00:00:00Z;
never reads wall-clock time. Tests may set any instant; monotonicity not enforced."""

from datetime import datetime, timezone

_DEFAULT_ISO = "2026-08-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._current = self._parse(_DEFAULT_ISO)

    @staticmethod
    def _parse(iso):
        if not isinstance(iso, str):
            raise ValueError("expected ISO 8601 string")
        s = iso.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt

    @staticmethod
    def format(dt):
        """ISO 8601 UTC with exactly three fractional digits."""
        dt = dt.astimezone(timezone.utc)
        ms = dt.microsecond // 1000
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + (".%03dZ" % ms)

    def now(self):
        return self._current

    def now_iso(self):
        return self.format(self._current)

    def today(self):
        return self.now().date().isoformat()

    def set(self, iso):
        self._current = self._parse(iso)
        return self._current


CLOCK = LogicalClock()
