"""In-memory data store (PRD §2.4).

Every entity collection is a plain dict keyed by UUID id. The store starts
EMPTY on every process boot — NO seeding, preloading, or hardcoded entities.
All data is created by tests through the declared API surface.

Common fields (id, created_at, updated_at, version) are managed here.
"""
import itertools
import uuid
from datetime import datetime, timezone

import clock
import timeutil

# One dict per entity collection. Keyed by id.
parcels = {}
crop_plans = {}
input_products = {}
input_lots = {}
application_records = {}
compliance_records = {}
planting_events = {}
harvest_events = {}
harvest_lots = {}
sale_contracts = {}
equipment_assets = {}
equipment_usages = {}
labor_entries = {}
irrigation_events = {}
applicators = {}

# Monotonic creation sequence so created_at ties (same millisecond) keep a
# stable, insertion-order sort. Used as the secondary sort key for lists and
# FIFO inventory ordering.
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def new_entity(extra_fields):
    """Create a record dict with common fields + the supplied field map.

    created_at/updated_at use real wall-clock UTC (resource minting timestamps,
    not the test-driving clock which only governs window math). version starts
    at 1 and increments on every persisted mutation (PRD §2.4).
    """
    now_real = datetime.now(timezone.utc)
    rec = {
        "id": new_id(),
        "created_at": timeutil.iso_now(now_real),
        "updated_at": timeutil.iso_now(now_real),
        "version": 1,
    }
    rec["_seq"] = next_seq()
    rec.update(extra_fields)
    return rec


def touch(rec):
    """Mark a record as mutated: refresh updated_at, bump version (PRD §2.4)."""
    rec["updated_at"] = timeutil.iso_now(datetime.now(timezone.utc))
    rec["version"] = rec.get("version", 0) + 1
