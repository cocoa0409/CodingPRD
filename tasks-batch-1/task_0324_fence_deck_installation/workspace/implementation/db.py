"""In-memory data store.

Every collection is a plain dict keyed by the resource id. The store starts
empty on every boot — no seeding, preloading, or hardcoded entities. The test
harness restarts the server before each test, which wipes all state.
"""
import threading
import uuid

import clock

# Global write lock — serialize mutations so cascading side effects stay atomic.
LOCK = threading.RLock()

# One dict per entity type, keyed by id.
customers = {}
projects = {}
estimates = {}
line_items = {}
site_measures = {}
permits = {}
hoa_approvals = {}
material_orders = {}
crew_bookings = {}
change_orders = {}
draws = {}
warranties = {}

# Monotonic sequence used only to break created_at ties deterministically.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def stamp_create(record, versioned=True):
    """Populate system fields on creation."""
    rid = new_id()
    ts = clock.now_iso()
    record["id"] = rid
    record["created_at"] = ts
    record["_seq"] = next_seq()
    if versioned:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version on mutation (PRD §2.4)."""
    if "version" in record:
        record["updated_at"] = clock.now_iso()
        record["version"] = record["version"] + 1
