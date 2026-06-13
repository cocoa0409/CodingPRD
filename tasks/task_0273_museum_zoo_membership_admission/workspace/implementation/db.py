"""In-memory data store. Starts EMPTY on every boot — no seeding.

Each entity type is a dict keyed by server-minted UUID. Records are plain dicts.
System fields (id/created_at/updated_at/version) are managed by helpers here.
"""
import uuid

import clock
from timeutil import format_iso

# One dict per entity collection, keyed by id.
patrons = {}
membership_plans = {}
memberships = {}
household_members = {}
guest_passes = {}
timed_entry_slots = {}
special_exhibits = {}
exhibit_sessions = {}
admission_orders = {}
admission_tickets = {}
reciprocal_partners = {}
donations = {}

# Monotonic counter so created_at tie-breaks are deterministic even when many
# rows share the same logical clock instant. Used as a secondary sort key.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return format_iso(clock.now())


def stamp_create(record):
    """Attach common system fields for a freshly created entity."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Mark a record mutated: bump version, refresh updated_at."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = now_iso()
    return record


def public(record):
    """Strip private bookkeeping keys (leading underscore) for serialization."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def reset_all():
    for coll in (
        patrons, membership_plans, memberships, household_members, guest_passes,
        timed_entry_slots, special_exhibits, exhibit_sessions, admission_orders,
        admission_tickets, reciprocal_partners, donations,
    ):
        coll.clear()
    global _seq
    _seq = 0
    clock.reset()
