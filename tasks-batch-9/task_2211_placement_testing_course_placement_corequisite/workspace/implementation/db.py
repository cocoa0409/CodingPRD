"""In-memory data store, logical clock and common system fields.

The store starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded here: every row is created by a client through a declared endpoint.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.5 -- before any client sets it, the logical clock reads exactly this.
LOGICAL_CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "students",
    "courses",
    "requisites",
    "rules",
    "administrations",
    "attempts",
    "determinations",
    "appeals",
    "sections",
    "registrations",
    "overrides",
    "studies",
)


class Store(object):
    def __init__(self):
        self.clock = LOGICAL_CLOCK_DEFAULT
        self._seq = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})

    # -- clock ------------------------------------------------------------
    def now(self):
        return self.clock

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_row():
    """Common system-managed properties (PRD 2.4)."""
    now = db.clock
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(row):
    """Refresh updated_at and bump version -- used for direct and cascaded
    mutations alike (PRD 2.4)."""
    row["updated_at"] = db.clock
    row["version"] = row["version"] + 1
    return row


def order_key(row):
    """Default list ordering: created_at ascending, insertion order breaking
    ties deterministically."""
    return (row["created_at"], row["_seq"])


def sort_rows(rows):
    return sorted(rows, key=order_key)
