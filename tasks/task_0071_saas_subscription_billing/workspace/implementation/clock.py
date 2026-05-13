"""Logical clock for deterministic time-based testing."""
from datetime import datetime, timezone, timedelta


class Clock:
    def __init__(self):
        # Initialize to a fixed point so tests can reason about cycle math.
        self._now = datetime.now(timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> datetime:
        self._now = self._now + timedelta(seconds=float(seconds))
        return self._now

    def set(self, dt: datetime):
        self._now = dt


clock = Clock()


def iso(dt: datetime) -> str:
    """Format datetime as ISO 8601 UTC with milliseconds (3 fractional digits)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # YYYY-MM-DDTHH:MM:SS.sssZ
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = int(dt.microsecond / 1000)
    return f"{s}.{millis:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse ISO 8601 string. Accepts trailing Z or +00:00 etc."""
    if s is None:
        return None
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
