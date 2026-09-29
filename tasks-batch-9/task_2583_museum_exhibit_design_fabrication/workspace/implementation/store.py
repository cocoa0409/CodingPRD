"""In-memory store and the explicit server-side logical clock (PRD §2.4).

The store starts completely EMPTY on every boot: no seeding, no preloading,
no hardcoded rows.  `start.sh` re-invocation therefore wipes every byte of state.
"""

import uuid
from datetime import datetime, timezone

# Before the clock is ever set it reads exactly 2026-08-01T00:00:00Z.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

KINDS = (
    "projects",
    "packages",
    "rounds",
    "votes",
    "zones",
    "cases",
    "artifacts",
    "interactives",
    "materials",
    "drawings",
    "windows",
    "punch_items",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for kind in KINDS:
            setattr(self, kind, {})
        self._seq = 0
        self.clock = DEFAULT_CLOCK

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())

    def now(self):
        return self.clock

    def set_clock(self, moment):
        self.clock = moment


db = Store()


def new_row(kind, fields, versioned=True):
    """Create a row dict with the four common properties (PRD §2.4)."""
    row = {
        "_kind": kind,
        "_seq": db.next_seq(),
        "id": db.new_id(),
        "created_at": db.now(),
    }
    if versioned:
        row["updated_at"] = db.now()
        row["version"] = 1
    row.update(fields)
    return row


def order_created(row):
    """Default deterministic ordering: created_at ascending, insertion order tie-break."""
    return (row["created_at"], row["_seq"])
