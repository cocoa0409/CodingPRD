"""Server-side logical clock.

PRD 2.4: all time-dependent behaviour reads a single server-side logical clock
rather than wall-clock time.  A freshly booted process starts the clock at
2026-08-01T00:00:00Z; POST /_clock/set_current_utc moves it.
"""

from datetime import datetime, timedelta, timezone

UTC = timezone.utc
DEFAULT_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class _Clock:
    def __init__(self):
        self.current = DEFAULT_INSTANT

    def set(self, instant):
        self.current = instant

    def now(self):
        return self.current


clock = _Clock()


def now():
    return clock.now()


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt(clock.now())


def parse(value):
    """Parse an ISO 8601 instant.  Raises ValueError when malformed."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def sec(dt):
    """Truncate to second granularity (PRD 2.4: comparisons resolve to seconds)."""
    if dt is None:
        return None
    return dt.replace(microsecond=0)


def days(n):
    return timedelta(days=n)
