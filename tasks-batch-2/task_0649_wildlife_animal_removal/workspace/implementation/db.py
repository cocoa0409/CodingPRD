"""In-memory data store (PRD §2.4).

Every resource carries a server-minted UUID `id`, a `created_at` (ISO 8601 UTC,
3 fractional digits), an `updated_at` (refreshed on every mutation), and an
integer `version` that begins at its initial value on creation and increments by
one on every mutation.

The store starts empty on every boot. NOTHING is seeded here.
"""
import itertools
import uuid

from clock import clock
from response import iso_ms

# One dict per entity type, keyed by id.
TABLES = [
    "species_profiles",
    "technicians",
    "service_accounts",
    "properties",
    "inspections",
    "entry_points",
    "quotes",
    "quote_line_items",
    "work_orders",
    "permits",
    "trap_placements",
    "capture_events",
    "exclusion_repairs",
    "monitoring_visits",
    "warranty_claims",
]

store = {t: {} for t in TABLES}

# Monotonic sequence to give a deterministic tiebreak for created_at sorting
# (the logical clock can produce identical timestamps within a single instant).
_seq = itertools.count(1)


def reset():
    for t in TABLES:
        store[t] = {}


def new_id():
    return str(uuid.uuid4())


def new_record(extra):
    now = iso_ms(clock.now())
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next(_seq),
    }
    rec.update(extra)
    return rec


def touch(rec):
    """Mark a resource mutated: refresh updated_at, bump version (PRD §2.4)."""
    rec["updated_at"] = iso_ms(clock.now())
    rec["version"] = rec.get("version", 1) + 1


def insert(table, rec):
    store[table][rec["id"]] = rec
    return rec


def get(table, rec_id):
    return store[table].get(rec_id)


def values(table):
    return list(store[table].values())
