"""In-memory data store and server-owned logical clock.

The store starts empty on every boot. No entity is ever seeded, preloaded,
or hardcoded at startup; every record is created through the declared API.
"""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.parades = {}
        self.route_segments = {}
        self.permits = {}
        self.endorsements = {}
        self.entries = {}
        self.floats = {}
        self.inspections = {}
        self.staging_areas = {}
        self.lineup_assignments = {}
        self.marshal_assignments = {}
        self.score_sheets = {}
        self.awards = {}
        self.sponsors = {}
        self.script_items = {}
        self.dispersal_plans = {}
        self.seq = 0
        # Logical clock startup default: exactly 2026-05-01T00:00:00Z.
        # It never falls back to wall-clock time.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


STORE = Store()
LOCK = threading.RLock()


def now():
    """Current logical-clock instant (timezone-aware UTC)."""
    return STORE.clock


def set_clock(dt):
    STORE.clock = dt


def next_seq():
    STORE.seq += 1
    return STORE.seq


def new_id():
    return str(uuid.uuid4())


def make_record():
    """Common system-managed properties for every resource."""
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    """Versioned mutation: version increments by exactly one, updated_at refreshes."""
    rec["version"] += 1
    rec["updated_at"] = now()
