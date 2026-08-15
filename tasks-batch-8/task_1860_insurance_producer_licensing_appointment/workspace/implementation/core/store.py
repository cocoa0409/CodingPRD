"""In-memory store.  Python dicts keyed by id; nothing touches disk.

The store starts completely empty on every boot: no entity is seeded,
preloaded, registered or hardcoded anywhere.  Every row the tests need is
created by the tests through the declared endpoints.
"""

import uuid

from .clock import parse_instant
from . import constants as K

COLLECTIONS = (
    "agencies",
    "producers",
    "licenses",
    "ce_credits",
    "appointments",
    "applications",
    "commission_entries",
    "regulatory_actions",
    "inquiries",
)


class Store(object):
    def __init__(self):
        self.now = parse_instant(K.DEFAULT_CLOCK_UTC)
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    def ordered(self, collection):
        """PRD 2.3: created_at ascending, ties broken by write order."""
        rows = getattr(self, collection).values()
        return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


db = Store()


def new_row(collection, fields):
    """Create a row with the common properties of PRD section 2.4."""
    row = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "created_at": db.now,
        "updated_at": db.now,
        "version": 1,
    }
    row.update(fields)
    getattr(db, collection)[row["id"]] = row
    return row


def bump(row):
    """Count the row as mutated: version + 1 and updated_at refreshed."""
    row["version"] = row["version"] + 1
    row["updated_at"] = db.now
    return row
