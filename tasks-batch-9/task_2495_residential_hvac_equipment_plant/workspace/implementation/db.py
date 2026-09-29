"""In-memory store and the logical plant clock (PRD 2.4, 2.5).

Everything lives in process memory only: no file, no sqlite, no cache.
Nothing is ever seeded here -- every row is created through the API.
"""

import threading
import uuid
from datetime import datetime, timezone

LOCK = threading.RLock()

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "programs",
    "standards",
    "platforms",
    "certs",
    "supplies",
    "lines",
    "orders",
    "warehouses",
    "reservations",
    "cells",
    "builds",
    "leak_tests",
    "run_tests",
    "claims",
    "capas",
)


class Store(object):
    def __init__(self):
        self.data = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        for name in COLLECTIONS:
            self.data[name] = {}

    # ---- clock -------------------------------------------------------
    def now(self):
        return self.clock

    def set_clock(self, value):
        self.clock = value

    def stamp(self):
        return fmt_instant(self.clock)

    def today(self):
        return self.clock.date()

    # ---- rows --------------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def insert(self, collection, row, versioned=True):
        row["id"] = str(uuid.uuid4())
        row["created_at"] = self.stamp()
        if versioned:
            row["updated_at"] = row["created_at"]
            row["version"] = 1
        row["_seq"] = self.next_seq()
        self.data[collection][row["id"]] = row
        return row

    def get(self, collection, row_id):
        if not isinstance(row_id, str):
            return None
        return self.data[collection].get(row_id)

    def rows(self, collection):
        """All rows of a collection in creation order."""
        return sorted(self.data[collection].values(), key=lambda r: r["_seq"])

    def touch(self, row):
        """One logical mutation of a row: refresh updated_at, bump version."""
        if "version" in row:
            row["updated_at"] = self.stamp()
            row["version"] = row["version"] + 1
        return row


def fmt_instant(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        "%03dZ" % (value.microsecond // 1000)
    )


db = Store()


def reset():
    """Only used by a fresh process boot; never exposed over HTTP."""
    global db
    db = Store()
