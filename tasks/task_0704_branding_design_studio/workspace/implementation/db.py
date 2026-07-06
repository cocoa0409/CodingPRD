"""In-memory data store.

Storage is in-memory only — plain Python dicts keyed by id. The store starts
EMPTY on every boot; nothing is seeded, preloaded, or hardcoded. Every entity is
created by the test suite via the declared API endpoints.
"""
import itertools

from clock import clock
from util import new_id, iso_now


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id. All empty at boot.
        self.studios = {}
        self.clients = {}
        self.projects = {}
        self.moodboards = {}
        self.concepts = {}
        self.milestones = {}
        self.invoices = {}
        self.deliverables = {}
        self.licenses = {}
        self.change_orders = {}
        self.retainers = {}
        self.care_cycles = {}
        # Monotonic counter to break created_at ties deterministically.
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def create(self, table, fields):
        """Insert a new record with system common fields (PRD §2.4).

        id (bare UUID), created_at, updated_at (ISO 8601 UTC, 3 fractional
        digits), version (starts at 1). _seq is an internal ordering key, not
        part of the response body.
        """
        rec = dict(fields)
        rec["id"] = new_id()
        ts = iso_now(clock.now())
        rec["created_at"] = ts
        rec["updated_at"] = ts
        rec["version"] = 1
        rec["_seq"] = self.next_seq()
        table[rec["id"]] = rec
        return rec

    def touch(self, rec):
        """Mark a record mutated: refresh updated_at, increment version (§2.4)."""
        rec["updated_at"] = iso_now(clock.now())
        rec["version"] = rec.get("version", 1) + 1
        return rec


db = Store()
