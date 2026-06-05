"""In-memory data store.

Storage is in-memory only — plain Python dicts keyed by id. The store starts
EMPTY on every boot; no entity is ever seeded, preloaded, or hardcoded. Every
entity is created by the test suite via the declared API surface.
"""
import uuid

from response import now_iso

# One dict per collection, keyed by the resource's server-minted id.
hotels = {}
room_types = {}
rooms = {}
rate_plans = {}
corporate_accounts = {}
guests = {}
group_blocks = {}
reservations = {}
folios = {}
incidentals = {}
night_audit_runs = {}

# Monotonic insertion counter so that created_at ties break deterministically
# in ascending creation order (PRD §2.3 default sort).
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def stamp_create(obj):
    """Set system fields at creation: id (if absent), created_at, updated_at, version."""
    ts = now_iso()
    if "id" not in obj or obj["id"] is None:
        obj["id"] = new_id()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = next_seq()
    return obj


def touch(obj):
    """Mutation bump: refresh updated_at and increment version by one (PRD §2.4/§2.9)."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj
