"""Server logical clock (PRD §3.9).

Starts at 2026-01-01T00:00:00Z on startup and never falls back to wall-clock
time once running. All sold_at / counted_at windows resolve against this clock.
The clock is reset to its startup default on every fresh process boot because
this module's state is in-memory only.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self):
        self.current = _DEFAULT

    def set(self, dt):
        self.current = dt

    def now(self):
        return self.current


clock = _Clock()


def now_iso():
    """ISO 8601 UTC with three fractional digits, used for response meta and
    resource timestamps (PRD §2.2 / §2.4). This uses the logical clock so all
    server-minted timestamps are deterministic and test-drivable."""
    return iso_z(clock.now())


def iso_z(dt):
    """Render a datetime as ISO 8601 UTC with exactly three fractional digits
    and a trailing Z."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}".format(dt.microsecond // 1000) + "Z"
