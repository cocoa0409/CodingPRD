"""In-memory data store. Everything lives in process memory only — no files,
no sqlite, no /tmp. Re-invoking start.sh wipes every byte of state.

The store starts completely empty; no entity is seeded at startup.
"""

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.7). Default is exactly 2026-08-01T00:00:00Z; the
# server must never fall back to wall-clock time.
# ---------------------------------------------------------------------------

_DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._current = _parse_iso(_DEFAULT_CLOCK_ISO)

    def now(self):
        return self._current

    def set(self, dt):
        self._current = dt


def _parse_iso(value):
    """Parse an ISO-8601 UTC timestamp (accepts trailing 'Z' or offsets)."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        raise ValueError("not an ISO timestamp")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso(value):
    return _parse_iso(value)


def format_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


CLOCK = LogicalClock()


def new_id():
    return str(uuid.uuid4())


def now_ts():
    return format_ts(CLOCK.now())


# ---------------------------------------------------------------------------
# Stores: dicts keyed by id. All start empty.
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.contest_events = {}
        self.categories = {}
        self.contestants = {}
        self.judges = {}
        self.entries = {}
        self.prejudging_slots = {}
        self.scoresheets = {}
        self.performance_slots = {}
        self.prize_awards = {}
        self.green_room_bookings = {}


DB = Store()


def reset_all():
    """Utility used only by tests of the server itself; never called at boot."""
    global DB, CLOCK
    DB = Store()
    CLOCK = LogicalClock()
