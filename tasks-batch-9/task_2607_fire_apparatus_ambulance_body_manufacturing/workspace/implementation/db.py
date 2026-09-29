"""In-memory data store.

Storage is process-local Python dictionaries only. The store is EMPTY on every
boot: nothing is seeded, preloaded or hardcoded. Every row any caller observes
was created through the declared API surface during that same process lifetime.
"""

import uuid

from flask import g

from timeutil import now_iso, parse_dt

# PRD §2.4 — mandatory logical-clock startup default. The server must never fall
# back to real wall-clock time for a business rule.
CLOCK_DEFAULT_RAW = "2026-08-01T00:00:00Z"


class Store(object):
    def __init__(self):
        self.programs = {}
        self.specifications = {}
        self.clauses = {}
        self.compliance_entries = {}
        self.unit_orders = {}
        self.slot_lines = {}
        self.reservations = {}
        self.plant_bays = {}
        self.trips = {}
        self.change_orders = {}
        self.certification_tests = {}
        self.warranty_startups = {}
        self._seq = 0
        self.clock_raw = CLOCK_DEFAULT_RAW

    # -- identity / ordering ------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    # -- logical clock -----------------------------------------------------
    @property
    def clock(self):
        return parse_dt(self.clock_raw)

    def set_clock(self, raw):
        self.clock_raw = raw


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_row(fields, versioned=True):
    """Mint a row: server id, created_at, and (unless immutable) updated_at/version."""
    row = {"id": new_id(), "created_at": now_iso()}
    row.update(fields)
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Record a mutation of `row`.

    PRD §2.5/§2.8: every row a write or a cascade touches has its `updated_at`
    refreshed and its `version` incremented by one — once per request, however
    many hops of the same cascade reach that row.
    """
    if row is None or "version" not in row:
        return row
    touched = getattr(g, "touched_rows", None)
    if touched is None:
        touched = set()
        g.touched_rows = touched
    key = id(row)
    if key in touched:
        return row
    touched.add(key)
    row["version"] = row["version"] + 1
    row["updated_at"] = now_iso()
    return row


def by_created_at(rows):
    """Deterministic ascending `created_at` order (§2.12); never reads `id`."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
