"""In-memory data store.

The store starts empty on every boot: no entity is ever seeded, preloaded or
hardcoded.  Every row is created by a client through the declared endpoints.

Rows are plain dicts.  Besides their domain fields every row carries:
  id          -- server minted UUID string
  created_at  -- logical-clock instant the row was first stored
  _seq        -- monotonic insertion counter; the deterministic tie-break for
                 "created_at ascending" ordering (the logical clock may not have
                 moved between two creations, so created_at alone is not a total
                 order).
Rows of entities that carry the common fields additionally hold updated_at and
version.  Corridor membership rows, turning movement counts and travel time runs
are append-only and deliberately carry neither (PRD section 2.4).
"""

import uuid

import clock


class Store(object):
    def __init__(self):
        self.intersections = {}
        self.corridors = {}
        self.corridor_members = {}
        self.requesters = {}
        self.complaints = {}
        self.projects = {}
        self.counts = {}
        self.runs = {}
        self.plans = {}
        self.phase_splits = {}
        self.ped_checks = {}
        self.priority_configs = {}
        self.observations = {}
        self.evaluations = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_row(common=True):
    """Fresh row scaffolding.  common=False -> append-only row (id/created_at only)."""
    row = {
        "id": new_id(),
        "created_at": clock.now(),
        "_seq": db.next_seq(),
    }
    if common:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1."""
    row["updated_at"] = clock.now()
    row["version"] = row.get("version", 1) + 1
    return row


def by_seq(rows):
    """created_at ascending (insertion order)."""
    return sorted(rows, key=lambda r: r["_seq"])
