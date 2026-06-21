"""In-memory data store.

Every collection is a plain dict keyed by the entity's UUID id. The store starts
EMPTY on every process boot — nothing is seeded, preloaded or hardcoded. Tests
build all preconditions through the declared API surface.

A monotonically increasing insertion sequence is recorded per record (``_seq``)
so that list endpoints can sort by creation order deterministically even when two
records share an identical created_at timestamp under a pinned logical clock.
"""

import uuid
from datetime import timezone

import clock
from timeutil import iso

# ---- Collections (all start empty) --------------------------------------
branches = {}
patrons = {}
titles = {}
copies = {}
loans = {}
holds = {}
reservations = {}
resources = {}
ill_requests = {}
license_pools = {}
ebook_loans = {}
fines = {}

ALL_COLLECTIONS = [
    branches, patrons, titles, copies, loans, holds, reservations,
    resources, ill_requests, license_pools, ebook_loans, fines,
]

_seq_counter = {"n": 0}


def _next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def new_id():
    return str(uuid.uuid4())


def stamp_create(record):
    """Attach id/created_at/updated_at/version/_seq to a freshly built record.

    created_at and updated_at follow the server logical clock (clock.now()).
    version starts at 1.
    """
    now = clock.now().astimezone(timezone.utc)
    record["id"] = new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = _next_seq()
    return record


def touch(record):
    """Mark a record mutated: refresh updated_at and bump version."""
    record["updated_at"] = clock.now().astimezone(timezone.utc)
    record["version"] = record.get("version", 1) + 1
    return record


def sorted_by_created(records):
    """Return records sorted by creation order (ascending), tie-break on _seq."""
    return sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def reset():
    """Clear every collection. Used only by the optional test-support reset hook;
    never called at startup."""
    for coll in ALL_COLLECTIONS:
        coll.clear()
    _seq_counter["n"] = 0
    clock.reset()
