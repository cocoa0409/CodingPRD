"""In-memory data store. Everything lives in process memory only.

The store starts completely empty on every boot. No seeding, no preload,
no persistence — start.sh re-invocation wipes every byte of state because
the process is fresh.
"""
import itertools
import threading
import uuid

from response import now_iso


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # One dict per entity type, keyed by id.
        self.projects = {}
        self.subscribers = {}
        self.enrollments = {}
        self.subscriptions = {}
        self.waitlist_entries = {}
        self.periods = {}
        self.allocations = {}
        self.reconciliations = {}
        self.rec_batches = {}
        self.carve_out_adjustments = {}
        # Monotonic counter so created_at ties have a deterministic order even
        # when wall-clock timestamps collide within the same millisecond.
        self._seq = itertools.count()

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)


# A single module-level store instance. Empty at import time.
store = Store()


def stamp_create():
    ts = now_iso()
    return {"created_at": ts, "updated_at": ts, "version": 1}


def touch(record):
    """Bump version and refresh updated_at on a mutation (PRD §2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
