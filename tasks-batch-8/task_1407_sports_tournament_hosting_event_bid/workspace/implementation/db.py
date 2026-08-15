"""In-memory data store and logical clock.

The store starts completely empty on every boot. No seeding, no preloading.
All business timestamps are stamped from the logical clock (STORE.clock),
which starts at exactly 2026-08-01T00:00:00Z and moves only via
POST /api/v1/_clock/set_current_utc. It never falls back to wall-clock time.
"""

import uuid
from datetime import date, datetime, timezone


class Store:
    def __init__(self):
        self.events = {}
        self.bids = {}
        self.requirements = {}
        self.venues = {}
        self.fields = {}
        self.hotel_blocks = {}
        self.room_bookings = {}
        self.divisions = {}
        self.teams = {}
        self.matches = {}
        self.officials = {}
        self.assignments = {}
        self.volunteers = {}
        self.shifts = {}
        self.signups = {}
        self.alerts = {}
        self.reports = {}
        self.settlements = {}
        self.seq = 0  # monotonic insertion counter (tiebreaks equal timestamps)
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


STORE = Store()


def new_id():
    return str(uuid.uuid4())


def new_seq():
    STORE.seq += 1
    return STORE.seq


def now():
    """Current logical instant (timezone-aware UTC)."""
    return STORE.clock


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits: 2026-08-01T00:00:00.000Z."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse a strict YYYY-MM-DD calendar date."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    return date.fromisoformat(s)


def base_entity():
    ts = iso(now())
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": new_seq(),
    }


def touch(obj):
    """Refresh updated_at and bump version (every mutation of a resource)."""
    obj["updated_at"] = iso(now())
    obj["version"] += 1
