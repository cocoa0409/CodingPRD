"""In-memory data store. Starts empty on every boot — nothing is seeded."""

import itertools
import threading
from datetime import datetime, timezone

from util import new_id

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "ports",
    "meeting_points",
    "port_calls",
    "tender_waves",
    "operators",
    "audits",
    "excursions",
    "departures",
    "guests",
    "bookings",
    "ledger",
    "incidents",
    "claims",
    "statements",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def now(self):
        return self.clock

    # ------------------------------------------------------------------
    # row lifecycle
    # ------------------------------------------------------------------
    def insert(self, collection, row, versioned=True):
        row["id"] = row.get("id") or new_id()
        row["created_at"] = self.clock
        row["_seq"] = self.next_seq()
        if versioned:
            row["updated_at"] = self.clock
            row["version"] = 1
        getattr(self, collection)[row["id"]] = row
        return row

    def touch(self, row):
        """Bump a row's mutation counter and refresh its updated_at."""
        row["version"] = row.get("version", 1) + 1
        row["updated_at"] = self.clock
        return row

    def ordered(self, collection):
        rows = list(getattr(self, collection).values())
        rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
        return rows


db = Store()
