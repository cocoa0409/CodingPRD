"""In-memory data store.

State is per-process and starts empty on every boot. No seeding, no disk
persistence — the test harness restarts the server before every test and
constructs all required entities through the declared API surface (PRD §2.x).

Common fields (PRD §2.4): every primary resource carries id (UUID, no prefix),
created_at, updated_at, and a version integer that begins at 1 and increments
by one on each mutation. Every entity listed in §2.4 is versioned — including
Quote.
"""
import threading
import uuid

from clock import now_real_iso


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # One dict per entity collection, keyed by id.
        self.shops = {}
        self.customers = {}
        self.decoration_methods = {}
        self.garment_styles = {}
        self.blank_skus = {}
        self.presses = {}
        self.embroidery_stations = {}
        self.orders = {}
        self.order_lines = {}
        self.art_proofs = {}
        self.blank_reservations = {}
        self.quotes = {}
        self.production_runs = {}
        # Monotonic sequence so created_at ties have a deterministic order.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())


# Module-level singleton. Reset only by process restart (per-test isolation).
store = Store()


def new_common_fields():
    """System-managed common fields for a primary resource (PRD §2.4).

    id, created_at, updated_at, version. The created_at/updated_at use the real
    server wall clock; the shop's logical `current_utc` (PRD §2.7) is a separate
    business field, not the resource timestamp.
    """
    now = now_real_iso()
    return {
        "id": store.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(record):
    """Refresh updated_at and bump version on a mutation (PRD §2.4)."""
    record["updated_at"] = now_real_iso()
    record["version"] = record.get("version", 1) + 1
