"""In-memory data store and logical clock.

The store starts completely empty on every boot. No entity is ever seeded,
preloaded, or hardcoded; every record is created through the declared API
surface. The logical clock starts at exactly 2026-08-01T00:00:00Z and never
falls back to wall-clock time.
"""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.projects = {}
        self.structure_surveys = {}
        self.abatements = {}
        self.utility_disconnects = {}
        self.permits = {}
        self.engineering_surveys = {}
        self.salvage_manifests = {}
        self.salvage_items = {}
        self.notifications = {}
        self.dust_logs = {}
        self.debris_tickets = {}
        self.backfill_plans = {}
        self.final_inspections = {}
        # Logical clock; startup default is exactly 2026-08-01T00:00:00Z.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Monotonic insertion sequence for stable created_at tie-breaking.
        self.seq = 0


store = Store()


def now():
    """Current logical time (aware UTC datetime)."""
    return store.clock


def next_seq():
    store.seq += 1
    return store.seq


def new_record():
    """Common system fields for a standard resource (id/created_at/updated_at/version)."""
    t = now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    """Every mutation bumps version by 1 and refreshes updated_at."""
    rec["version"] += 1
    rec["updated_at"] = now()
