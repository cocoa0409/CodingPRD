"""In-memory data store.

One dict per entity type, keyed by id. The store starts empty on every boot —
no seeding. UUIDs and common system fields (created_at, updated_at, version) are
managed here.
"""
import uuid

import clock

# --- entity tables ---
venues = {}
sections = {}
events = {}
sellers = {}
buyers = {}
listings = {}
seats = {}
orders = {}
transfers = {}
payouts = {}
guarantee_claims = {}
event_credits = {}
fraud_flags = {}

TABLES = {
    "venue": venues,
    "section": sections,
    "event": events,
    "seller": sellers,
    "buyer": buyers,
    "listing": listings,
    "seat": seats,
    "order": orders,
    "transfer": transfers,
    "payout": payouts,
    "guarantee_claim": guarantee_claims,
    "event_credit": event_credits,
    "fraud_flag": fraud_flags,
}

# idempotency registry: key -> { "params": {...}, "order_id": "..." }
idempotency_keys = {}


def new_id():
    return str(uuid.uuid4())


def stamp_create(record):
    """Set system fields on a brand-new record."""
    ts = clock.now_iso()
    record.setdefault("id", new_id())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """Mark a record mutated: refresh updated_at, bump version by exactly 1."""
    record["updated_at"] = clock.now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


def reset():
    for t in TABLES.values():
        t.clear()
    idempotency_keys.clear()
