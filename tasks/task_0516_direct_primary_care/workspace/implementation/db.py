"""In-memory data store.

All state is held in module-level dicts keyed by id. The store starts EMPTY on
every process boot; nothing is seeded. Tests build all data via the API.
"""
import itertools
import uuid

from clock import clock
from timeutil import to_iso

# One dict per entity type, keyed by id.
practices = {}
providers = {}
employers = {}
members = {}
memberships = {}
employer_seats = {}
visit_slots = {}
visits = {}
care_plans = {}
referrals = {}
message_threads = {}
invoices = {}
payments = {}

# Monotonic sequence to provide a stable creation order independent of identical
# logical-clock timestamps (used for created_at ASC tie-breaks).
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def common_fields():
    """System-managed common fields at creation: created_at, updated_at, version."""
    now = clock.now()
    return {
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def touch(entity):
    """Advance updated_at to the current clock and increment version."""
    entity["updated_at"] = clock.now()
    entity["version"] = entity.get("version", 1) + 1
