"""In-memory data store. Everything lives in process memory keyed by id.

The store starts EMPTY on every boot. Nothing is seeded, preloaded, or
hardcoded — every entity is built by tests via the declared API surface.
"""
import uuid

from clock import Clock, format_iso8601_ms


class DB:
    def __init__(self):
        self.customers = {}
        self.projects = {}
        self.measures = {}
        self.quotes = {}
        self.addons = {}
        self.change_orders = {}
        self.material_orders = {}
        self.crews = {}
        self.install_jobs = {}
        self.warranty_claims = {}
        self.financing_applications = {}
        self.clock = Clock()
        # monotonic sequence to break created_at ties for stable ascending sort
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


def new_id():
    return str(uuid.uuid4())


def common_fields(db):
    """Build the system-managed common-field set for a new resource.

    PRD §2.4: id (UUID, no prefix), created_at, updated_at (ISO8601 UTC, 3
    fractional digits), version starting at the creation value and
    incrementing by one on every modification.
    """
    now = format_iso8601_ms(db.clock.now)
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(db, entity):
    """Refresh updated_at and bump version on a mutation (PRD §2.4, §2.5)."""
    entity["updated_at"] = format_iso8601_ms(db.clock.now)
    entity["version"] = entity["version"] + 1


# Single global store. Constructed fresh on import (process start) — empty.
store = DB()
