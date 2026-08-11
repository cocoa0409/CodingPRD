"""In-memory store.  Nothing is ever seeded: every row arrives through the
declared endpoints, and a fresh process starts with every collection empty."""

import uuid

from constants import CLOCK_DEFAULT_UTC
from timeutil import parse_instant

COLLECTIONS = (
    "agencies",
    "oris",
    "service_types",
    "sites",
    "devices",
    "device_assignments",
    "applicants",
    "appointments",
    "cards",
    "positions",
    "submissions",
    "chr_responses",
    "determinations",
    "subscriptions",
    "notifications",
    "assessments",
    "invoices",
)


class Store:
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = parse_instant(CLOCK_DEFAULT_UTC)
        self._touched = set()

    # -- clock ---------------------------------------------------------------
    def now(self):
        return self.clock

    def set_clock(self, instant):
        self.clock = instant

    # -- identity ------------------------------------------------------------
    @staticmethod
    def new_id():
        return str(uuid.uuid4())

    # -- request scoped bump bookkeeping -------------------------------------
    def begin_request(self):
        self._touched_set()

    def _touched_set(self):
        """Request-scoped so concurrent requests never share bump state."""
        try:
            from flask import g, has_request_context

            if has_request_context():
                if not hasattr(g, "touched_rows"):
                    g.touched_rows = set()
                return g.touched_rows
        except RuntimeError:
            pass
        return self._touched

    def create(self, collection, fields):
        row = dict(fields)
        row["id"] = self.new_id()
        row["created_at"] = self.clock
        row["updated_at"] = self.clock
        row["version"] = 1
        getattr(self, collection)[row["id"]] = row
        self._touched_set().add(row["id"])
        return row

    def touch(self, row):
        """Advance version by exactly one and refresh updated_at -- once per
        request per row, never once per cascade leg (PRD 2.5)."""
        if row is None:
            return
        touched = self._touched_set()
        key = row["id"]
        if key in touched:
            row["updated_at"] = self.clock
            return
        touched.add(key)
        row["version"] = row.get("version", 0) + 1
        row["updated_at"] = self.clock


db = Store()
