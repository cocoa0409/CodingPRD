"""In-memory data store (PRD §2.4).

All state lives in module-level dicts keyed by UUID id. The store starts empty
on every process boot and is never seeded. Each restart wipes all state.

Every primary resource carries:
- id: UUID without type prefix
- created_at: ISO 8601 UTC, millisecond precision
- updated_at: ISO 8601 UTC, millisecond precision (refreshed on every mutation)
- version: integer starting at 1, incremented on every mutation
"""
import uuid
import itertools

import timeutil

# One dict per entity collection, keyed by id.
plans = {}
shipping_zones = {}
recipes = {}
members = {}
subscriptions = {}
weekly_boxes = {}
box_recipes = {}
referrals = {}

# Monotonic sequence to provide a stable secondary sort key when two resources
# share an identical created_at timestamp. created_at is the primary sort key
# (PRD §2.3); this preserves insertion order for ties.
_seq = itertools.count()


def new_id():
    return str(uuid.uuid4())


def stamp_create(now):
    """Return the system-managed audit fields for a freshly created resource."""
    ts = timeutil.now_iso(now)
    return {
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_seq),
    }


def touch(entity, now):
    """Mark a resource as mutated: refresh updated_at and bump version."""
    entity["updated_at"] = timeutil.now_iso(now)
    entity["version"] = entity.get("version", 1) + 1
