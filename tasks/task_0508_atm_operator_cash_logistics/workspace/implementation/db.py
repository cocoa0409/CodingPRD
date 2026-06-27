"""In-memory data store. All entities are plain dicts keyed by id.

The store starts EMPTY on every process boot — no seeding. Tests build every
precondition through the declared API surface. A single module-level `store`
instance is shared by all routes.
"""
from clock import Clock
from util import iso_now, new_id


# Entity collections. Each maps id -> entity dict.
_COLLECTIONS = [
    "site_merchants",
    "vaults",
    "routes",
    "locations",
    "atms",
    "cassettes",
    "replenishment_orders",
    "transactions",
    "cash_counts",
    "service_tickets",
    "settlement_runs",
    "commission_statements",
    "fee_disclosures",
]


class Store:
    def __init__(self):
        self.clock = Clock()
        for name in _COLLECTIONS:
            setattr(self, name, {})
        # Monotonic insertion counter so list endpoints can sort by true
        # creation order even when several entities share a clock timestamp.
        self._seq = 0

    # -- creation helpers ----------------------------------------------------
    def _next_seq(self):
        self._seq += 1
        return self._seq

    def stamp_new(self, entity, common_fields=True):
        """Attach system-managed fields on create.

        common_fields=True -> id, created_at, updated_at, version (PRD §2.4).
        common_fields=False -> id + created_at only (Transaction is append-only).
        """
        now = iso_now(self.clock.get())
        entity["id"] = new_id()
        entity["created_at"] = now
        entity["_seq"] = self._next_seq()
        if common_fields:
            entity["updated_at"] = now
            entity["version"] = 1
        return entity

    def clock_now_iso(self):
        return iso_now(self.clock.get())

    def touch(self, entity):
        """Refresh updated_at and bump version on any mutation (PRD §2.5)."""
        entity["updated_at"] = iso_now(self.clock.get())
        if "version" in entity:
            entity["version"] = entity["version"] + 1
        return entity

    # -- ordered listing -----------------------------------------------------
    @staticmethod
    def sorted_values(collection):
        """Creation-ascending order (PRD §2.3)."""
        return sorted(collection.values(), key=lambda e: e["_seq"])


# Singleton store for the process.
store = Store()
