"""In-memory data store (PRD §2.4, §2.6).

Storage is in-memory ONLY — plain dicts keyed by id. There is NO persistence,
no SQLite, no JSON dump, no /tmp cache. Every process boot starts empty; the
store is NEVER seeded or preloaded with any entity. Tests build all state via
the declared API surface.

Common system fields (PRD §2.4):
  - id              : server-minted UUID, no prefix
  - created_at      : ISO 8601 UTC, three fractional digits (logical clock)
  - updated_at      : same
  - version         : integer, begins at 1, +1 on every mutation
LoyaltyLedgerEntry is the one exception: append-only, only id + created_at.
"""

import uuid

from clock import clock


class DB:
    def __init__(self):
        # One dict per mutable entity collection, keyed by id.
        self.loyalty_members = {}
        self.paint_bar_items = {}
        self.studio_visits = {}
        self.bisque_pieces = {}
        self.kiln_batches = {}
        self.party_bookings = {}
        self.class_series = {}
        self.enrollments = {}
        self.ledger_entries = {}
        # Supply consume lines (not a top-level REST resource, but needed for
        # void compensation and supplies_subtotal recomputation).
        # keyed by line id -> {id, visit_id, paint_bar_item_id, qty,
        #                      charge_cents, voided, created_at}
        self.supply_lines = {}
        # Monotonic counter to break created_at ties deterministically so that
        # list ordering by created_at is stable even when many records share the
        # same logical-clock instant.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    @staticmethod
    def new_id():
        return str(uuid.uuid4())


db = DB()


def new_id():
    return DB.new_id()


def stamp_common(record):
    """Initialise common system fields on a freshly created mutable record."""
    now = clock.now_iso()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Mark a mutable record as mutated: refresh updated_at, bump version.

    PRD §2.6: recomputing a derived field on its owning resource is a mutation
    that refreshes updated_at and increments version.
    """
    record["updated_at"] = clock.now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
