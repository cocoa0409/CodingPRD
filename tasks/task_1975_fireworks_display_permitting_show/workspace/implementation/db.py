"""In-memory data store and the logical clock.

The store starts completely empty on every boot — no seed data of any kind.
The logical clock starts at exactly 2026-08-01T00:00:00Z and never falls back
to wall-clock time; it only moves via POST /pyro/_clock/set_current_utc.
"""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0  # monotonic insertion counter; deterministic tiebreak for created_at ASC
        self.operators = {}
        self.crew_members = {}
        self.displays = {}
        self.site_plans = {}
        self.permit_applications = {}
        self.magazines = {}
        self.batches = {}
        self.movements = {}
        self.weather_readings = {}
        self.security_posts = {}
        self.misfires = {}
        self.sweeps = {}
        self.incidents = {}


store = Store()


def new_id():
    return str(uuid.uuid4())


def new_record(with_version=True):
    """Base fields for a fresh record. `_seq` is internal (never serialized)."""
    store.seq += 1
    rec = {"id": new_id(), "created_at": store.clock, "_seq": store.seq}
    if with_version:
        rec["updated_at"] = store.clock
        rec["version"] = 1
    return rec


def bump(rec):
    """Refresh updated_at and increment version after a mutation."""
    rec["updated_at"] = store.clock
    rec["version"] += 1
