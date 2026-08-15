"""In-memory data store and the server-controlled logical clock.

The store starts empty on every boot. No seeding of any kind.
The logical clock defaults to exactly 2026-08-01T00:00:00Z and never
falls back to wall-clock time.
"""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.facilities = {}
        self.beds = {}
        self.physicians = {}
        self.admissions = {}
        self.transfers = {}
        self.holds = {}
        self.assignments = {}
        self.diversions = {}
        self.boarding = {}
        self.huddles = {}
        self.forecasts = {}
        self.seq = 0
        # Logical clock: startup default pinned by the PRD.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()


def now():
    """Current logical-clock time (timezone-aware UTC)."""
    return db.clock


def set_clock(dt):
    db.clock = dt.astimezone(timezone.utc)


def next_seq():
    db.seq += 1
    return db.seq


def new_entity():
    """Common system-managed fields for every resource."""
    ts = now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    """Every mutation refreshes updated_at and increments version."""
    entity["updated_at"] = now()
    entity["version"] += 1
