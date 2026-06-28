"""In-memory data store (no persistence; wiped on every fresh boot).

Each entity collection is a plain dict keyed by the entity's UUID id. NOTHING
is seeded here — every entity is created by the API surface. Insertion order is
preserved by dict ordering, which we rely on for created_at-ascending listing.
"""
import uuid
from datetime import datetime, timezone

from clock import clock


def new_id():
    return str(uuid.uuid4())


def _ts(dt):
    # ISO 8601 UTC with three fractional digits (PRD §2.4).
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    """Holds every entity collection. A fresh Store == a blank world."""

    def __init__(self):
        self.members = {}
        self.guides = {}
        self.trails = {}
        self.units = {}
        self.gear_items = {}
        self.tour_departures = {}
        self.guide_assignments = {}
        self.reservations = {}
        self.settlements = {}
        self.closure_events = {}
        # Monotonic creation sequence so created_at ties keep a stable order.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now_iso():
    """Wall-clock UTC stamp for created_at/updated_at (server-managed audit time)."""
    return _ts(datetime.now(timezone.utc))


def clock_iso():
    """Logical-clock stamp for domain timestamps (waiver_signed_at, checked_out_at, returned_at)."""
    return _ts(clock.now())


def stamp_common_create(record):
    """Attach the full id/created_at/updated_at/version quartet (PRD §2.4)."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["updated_at"] = record["created_at"]
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def stamp_lightweight_create(record):
    """Lightweight audit record: only id and created_at (PRD §2.4)."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Mutation bump: refresh updated_at and increment version (PRD §2.4/§2.5)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
