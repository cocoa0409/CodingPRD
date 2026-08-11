"""In-memory data store.

Plain Python dicts only.  The store starts EMPTY on every boot: no entity is
ever seeded, preloaded or hardcoded.  Every row any caller needs is built
through the declared endpoints.
"""

import threading

from . import ids
from .timeutil import clock

# One dict per entity type, keyed by id.
TABLES = (
    "barns",
    "clients",
    "horses",
    "limb_states",
    "farriers",
    "shoe_skus",
    "inventory_buckets",
    "stock_transfers",
    "shoe_reservations",
    "rate_cards",
    "routes",
    "route_stops",
    "appointments",
    "service_lines",
    "lameness_cases",
    "vet_prescriptions",
    "invoices",
    "invoice_lines",
    "reminders",
)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in TABLES:
            setattr(self, name, {})
        self._seq = 0
        clock.reset()
        ids.reset()

    def next_seq(self):
        self._seq += 1
        return self._seq

    # -- row lifecycle ------------------------------------------------------
    def mint(self, table, fields, versioned=True):
        """Create a row with its system fields.

        ``created_at`` (and ``updated_at``) are server-minted instants taken
        from the logical clock.  ``_seq`` records mint order so that rows
        sharing a ``created_at`` tie-break in the order they were minted.
        """
        row = dict(fields)
        row["id"] = ids.new_id()
        row["created_at"] = clock.instant()
        row["_seq"] = self.next_seq()
        row["_table"] = table
        if versioned:
            row["updated_at"] = row["created_at"]
            row["version"] = 1
        getattr(self, table)[row["id"]] = row
        return row

    def touch(self, row):
        """Record one declared mutation step of a row."""
        row["updated_at"] = clock.instant()
        row["version"] = row.get("version", 1) + 1
        return row

    # -- lookup helpers -----------------------------------------------------
    def get(self, table, row_id):
        if not isinstance(row_id, str):
            return None
        return getattr(self, table).get(row_id)

    def all(self, table):
        """Every row of a table in canonical order: created_at asc, mint order."""
        return sorted(getattr(self, table).values(), key=order_key)

    def where(self, table, **equals):
        rows = []
        for row in getattr(self, table).values():
            if all(row.get(k) == v for k, v in equals.items()):
                rows.append(row)
        rows.sort(key=order_key)
        return rows


def order_key(row):
    """Canonical list ordering: created_at ascending, then mint order.

    ``id`` is never a sort key (PRD 2.3).
    """
    return (row["created_at"], row["_seq"])


db = Store()
