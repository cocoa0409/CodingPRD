"""In-memory data store and the logical clock (PRD sections 2.4 and 2.5).

The store is empty on every boot: no seeding, no preloading, no persistence.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.5: the server starts with the logical clock at exactly this instant and
# never falls back to wall-clock time for any comparison, stamp or expiry.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.models = {}
        self.programs = {}
        self.dossiers = {}
        self.parts = {}
        self.stations = {}
        self.technicians = {}
        self.builds = {}
        self.logs = {}
        self.distributors = {}
        self.quotes = {}
        self.quote_lines = {}
        self.claims = {}
        self.now = CLOCK_START
        self._seq = itertools.count(1)

    def seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_row(versioned=True):
    """Common system fields (PRD 2.4)."""
    row = {"id": new_id(), "created_at": db.now}
    if versioned:
        row["updated_at"] = db.now
        row["version"] = 1
    row["_seq"] = db.seq()
    return row


def bump(row):
    """A mutation of one row: refresh updated_at and advance version by 1."""
    row["updated_at"] = db.now
    row["version"] = row["version"] + 1


def order_created_asc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def order_created_desc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)


def by_key(rows, *keys):
    return sorted(rows, key=lambda r: tuple(r[k] for k in keys) + (r["_seq"],))
