"""In-memory data store. The store starts empty on every boot — nothing is
seeded, preloaded, or hardcoded. Every entity is constructed via the API."""

import uuid

import clock

# Entity stores, keyed by id.
plants = {}
customers = {}
categories = {}
par_levels = {}
routes = {}
stops = {}
carts = {}
sort_batches = {}
sort_items = {}
wash_loads = {}
finish_runs = {}
garments = {}
deliveries = {}
discrepancies = {}
invoices = {}
utility_readings = {}

# Unbilled lost-item charge queue: {id, customer_id, charge_cents, invoice_id}.
# invoice_id is None while unbilled; set to the invoice that drained it.
lost_queue = []

# Plant-level clean stock ledger: (customer_id, category_id) -> pieces.
clean_stock = {}

# Monotonic insertion sequence — stable tie-break for created_at ordering.
_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_entity(common=True):
    """Mint a new entity skeleton with id/created_at (+updated_at/version unless
    the entity is immutable like UtilityReading)."""
    ts = clock.fmt(clock.now())
    e = {"id": str(uuid.uuid4()), "created_at": ts, "_seq": next_seq()}
    if common:
        e["updated_at"] = ts
        e["version"] = 1
    return e


def touch(e):
    """Refresh updated_at and increment version on a mutated resource."""
    e["updated_at"] = clock.fmt(clock.now())
    e["version"] += 1


def public(e):
    """Strip internal (underscore-prefixed) fields before serialization."""
    return {k: v for k, v in e.items() if not k.startswith("_")}


def sorted_all(store):
    """All entities sorted by created_at ascending (insertion order breaks ties)."""
    return sorted(store.values(), key=lambda e: (e["created_at"], e["_seq"]))
