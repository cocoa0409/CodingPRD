"""In-memory data store (PRD 2.4).

Storage is in-memory only: Python dicts keyed by id. The store starts EMPTY on
every boot — no entity is seeded, preloaded, or hardcoded at startup. Every
entity any test needs is constructed by the test itself via the declared API
surface. A fresh process therefore carries no state from any previous run.
"""

import uuid

from clock import LogicalClock


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id (UUID, no type prefix).
        self.patients = {}
        self.panels = {}
        self.tests = {}
        self.plans = {}
        self.lots = {}
        self.vials = {}
        self.visits = {}
        self.billing_entries = {}
        # Single logical clock for the whole process.
        self.clock = LogicalClock()

    @staticmethod
    def new_id():
        # Server-minted UUID with no type prefix (PRD 2.4).
        return str(uuid.uuid4())


# Module-level singleton. NOTE: created empty — never seeded.
store = Store()


def stamp_create(entity):
    """Set common system fields on creation (PRD 2.4).

    created_at / updated_at are ISO 8601 UTC with three fractional digits taken
    from the logical clock; version begins at 1 and increments by one on every
    mutation.
    """
    now = store.clock.now_iso_ms()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


def touch(entity):
    """Record a mutation: refresh updated_at and increment version (PRD 2.4).

    'Mutation' includes reconciliation of derived fields.
    """
    entity["updated_at"] = store.clock.now_iso_ms()
    entity["version"] = entity.get("version", 0) + 1
    return entity
