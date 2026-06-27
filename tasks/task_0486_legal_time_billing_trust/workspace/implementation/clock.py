"""The server's logical clock and ISO 8601 helpers.

The clock is the single source of "now" for collections aging. Wall-clock time
is NEVER consulted for business logic — only this logical clock. Before any
/_clock/set_current_utc call the clock reads 2026-01-01T00:00:00Z.

All state is process-local; a fresh boot resets the clock to its default.
"""

from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"


def parse_iso8601(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive strings are treated as
    UTC. Raises ValueError on anything unparseable.
    """
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso8601(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def server_now_iso():
    """A monotonically increasing wall-ish timestamp for created_at/updated_at.

    These system audit fields use real time so that creation order is
    distinguishable; the LOGICAL clock governs business aging instead.
    """
    return format_iso8601(datetime.now(timezone.utc))


class LogicalClock:
    def __init__(self):
        self._now = parse_iso8601(DEFAULT_CLOCK_ISO)

    def now(self):
        """Return the current logical instant as an aware datetime (UTC)."""
        return self._now

    def now_iso(self):
        return format_iso8601(self._now)

    def set(self, dt):
        self._now = dt


# A single process-local clock instance.
clock = LogicalClock()
