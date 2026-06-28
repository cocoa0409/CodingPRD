"""In-memory data store (PRD: API correctness, no durability).

Every collection is a plain dict keyed by the entity's UUID `id`. The store
starts EMPTY on every boot — nothing is seeded, preloaded, or hardcoded. Tests
build all preconditions through the declared API surface.

A monotonic `_seq` counter stamps each record with a creation sequence number so
list ordering by creation order is stable even when many records are created at
the same logical-clock (or wall-clock) instant.
"""
import threading
import uuid

# One dict per entity type, keyed by id.
counties = {}
parcels = {}
investors = {}
sales = {}
listings = {}
bids = {}
certificates = {}
sub_taxes = {}
redemptions = {}
assignments = {}
deed_applications = {}
surplus_distributions = {}

_lock = threading.RLock()
_seq = 0


def next_seq():
    global _seq
    with _lock:
        _seq += 1
        return _seq


def new_id():
    return str(uuid.uuid4())


def lock():
    return _lock
