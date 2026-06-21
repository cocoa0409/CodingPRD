"""In-memory data store (PRD §2.4).

All state lives in module-level dicts keyed by id. There is NO seeding: every
collection starts empty on each fresh process boot. The test harness rebuilds
all entities via the declared API surface before every test.
"""
import uuid

import clock

# One dict per entity type, keyed by string id.
customers = {}
technicians = {}
membership_plans = {}
memberships = {}
material_skus = {}
truck_stock_items = {}
service_jobs = {}
estimates = {}
dispatches = {}
permits = {}
material_usages = {}
invoices = {}
callbacks = {}

ALL_COLLECTIONS = [
    customers,
    technicians,
    membership_plans,
    memberships,
    material_skus,
    truck_stock_items,
    service_jobs,
    estimates,
    dispatches,
    permits,
    material_usages,
    invoices,
    callbacks,
]

# Monotonic creation sequence — guarantees a deterministic, stable insertion
# order even when several records share the same logical-clock created_at.
# Used as the tie-break for generic created_at-ASC list ordering. NOT used for
# the dispatch queue, which (per PRD §3.10) breaks ties on created_at only.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def reset():
    global _seq
    for c in ALL_COLLECTIONS:
        c.clear()
    _seq = 0
    clock.reset()


def new_id():
    """Server-minted UUID id with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def stamp_new(record):
    """Set common fields on a freshly created entity (PRD §2.4).

    id, created_at, updated_at (ISO 8601 UTC, 3 fractional digits), version=1.
    """
    ts = clock.now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    # Internal-only ordering key (stripped before serialization).
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Bump updated_at to current server time and increment version (PRD §2.4)."""
    record["updated_at"] = clock.now_iso()
    record["version"] = record["version"] + 1
    return record
