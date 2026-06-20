"""In-memory data store. Starts empty on every boot — no seeded/preloaded data.

Each entity collection is a dict keyed by UUID id. Common fields (id, created_at,
updated_at, version) are managed here (PRD §2.4).
"""
import itertools
import uuid

from clock import now_iso8601

# One dict per entity type, keyed by id.
agencies = {}
caregivers = {}
clients = {}
care_plans = {}
care_tasks = {}
matches = {}
visits = {}
mileage_entries = {}
invoices = {}
ltc_claims = {}

# Monotonic counter to provide a stable secondary sort by creation order and to
# break created_at ties deterministically (timestamps have ms resolution).
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def stamp_new(obj):
    """Attach the four common fields to a freshly-created entity."""
    ts = now_iso8601()
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = next(_seq)
    return obj


def touch(obj):
    """Refresh updated_at and bump version on any mutation (PRD §2.4)."""
    obj["updated_at"] = now_iso8601()
    obj["version"] = obj.get("version", 1) + 1
    return obj


def public(obj):
    """Return a copy of an entity with internal-only fields stripped."""
    return {k: v for k, v in obj.items() if not k.startswith("_")}
