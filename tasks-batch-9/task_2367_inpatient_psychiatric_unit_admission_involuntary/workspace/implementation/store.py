"""In-memory data store and the server-held logical clock.

The store starts completely EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded: every entity is created by a client through the declared API surface.
"""

import uuid
from datetime import datetime, timezone

# PRD §2.4 — at process startup the logical clock holds exactly 2026-08-01T00:00:00Z.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "clinicians",
    "units",
    "beds",
    "patients",
    "evaluations",
    "holds",
    "petitions",
    "hearings",
    "admissions",
    "restraints",
    "capacity_determinations",
    "medication_consents",
    "discharge_requests",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.current_utc = DEFAULT_CLOCK
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def now(self):
        return self.current_utc

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_row():
    """Common resource properties (PRD §2.5): id, created_at, updated_at, version."""
    now = db.now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(row):
    """Register a mutation: refresh updated_at and increment version by exactly 1."""
    row["updated_at"] = db.now()
    row["version"] = row["version"] + 1


def sort_key(row):
    return (row["created_at"], row["_seq"])


def ordered(rows):
    return sorted(rows, key=sort_key)
