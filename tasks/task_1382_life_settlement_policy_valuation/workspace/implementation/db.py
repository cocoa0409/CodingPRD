"""In-memory data store and the provider-controlled logical clock.

The store starts empty on every boot; nothing is seeded. All temporal logic
reads `store.clock`, never wall-clock time.
"""

import threading
import uuid
from datetime import datetime, timezone

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# Serializes request handling so multi-entity cascades are atomic.
REQUEST_LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.clock = CLOCK_DEFAULT
        self.seq = 0
        for name in (
            "brokers",
            "investors",
            "insureds",
            "licenses",
            "policies",
            "cases",
            "screenings",
            "le_reports",
            "offers",
            "packages",
            "escrows",
            "disbursements",
            "schedules",
            "payments",
            "tracking_events",
            "death_claims",
            "portfolios",
            "snapshots",
        ):
            setattr(self, name, {})

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def stamp(entity, immutable=False):
    """Populate system fields on a freshly created entity."""
    ts = store.clock
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["_seq"] = store.next_seq()
    if not immutable:
        entity["updated_at"] = ts
        entity["version"] = 1


def touch(entity):
    """Any mutation refreshes updated_at and increments version (PRD §2.10)."""
    entity["updated_at"] = store.clock
    entity["version"] += 1


def now():
    return store.clock
