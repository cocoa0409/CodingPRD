"""In-memory data store (PRD: API correctness, no durability).

Every collection is a plain dict keyed by id. The store starts EMPTY on every
process boot — nothing is seeded, preloaded, or hardcoded. All entities are
created exclusively through the declared API surface.
"""
import itertools
import threading

from util import new_id, iso_now
from clock import now as clock_now


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # one dict per primary collection, keyed by id
        self.wineries = {}
        self.batches = {}
        self.products = {}
        self.releases = {}
        self.members = {}
        self.memberships = {}
        self.shipments = {}
        self.tasting_orders = {}
        self.reservations = {}
        self.distribution_orders = {}
        self.ledger_entries = {}
        # monotonic counter to break creation-timestamp ties deterministically
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def common_fields():
    """System-managed fields for a freshly created primary resource (PRD §2.4)."""
    ts = iso_now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(entity):
    """Mark a primary resource mutated: bump version, refresh updated_at (PRD §2.4)."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = iso_now()


def ledger_event_fields():
    """An immutable ledger entry carries only id + created_at (PRD §2.4)."""
    return {
        "id": new_id(),
        "created_at": iso_now(),
        "_seq": db.next_seq(),
    }
