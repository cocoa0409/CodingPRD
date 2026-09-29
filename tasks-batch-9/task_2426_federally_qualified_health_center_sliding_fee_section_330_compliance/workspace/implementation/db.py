"""In-memory data store and the logical compliance clock.

The store starts completely empty on every boot: nothing is seeded, preloaded or
hardcoded here.  Every row any caller sees was created through the declared API.
"""

import itertools
import threading
import uuid
from datetime import datetime, timezone

# PRD 2.5: the logical clock's value at process startup is exactly this instant.
STARTUP_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# One global lock serialises requests so multi-hop cascades stay atomic.
LOCK = threading.RLock()

COLLECTIONS = (
    "health_centers",
    "poverty_guidelines",
    "board_members",
    "service_sites",
    "service_definitions",
    "scope_change_requests",
    "fee_schedules",
    "discount_tiers",
    "patients",
    "income_verifications",
    "encounters",
    "waivers",
    "uds_reports",
    "quality_measure_results",
    "site_visit_findings",
    "corrective_action_plans",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = STARTUP_CLOCK
        self._seq = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})


db = Store()


def now():
    """The logical clock.  Never wall-clock time."""
    return db.clock


def set_clock(value):
    db.clock = value


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(db._seq)


def base_row(versioned=True):
    """id / created_at (+ updated_at, version) common fields of PRD 2.4.

    ``_seq`` is an internal insertion counter used only to break ties when two
    rows of one entity share a created_at instant; it is never serialised.
    """
    row = {"id": new_id(), "created_at": now(), "_seq": next_seq()}
    if versioned:
        row["updated_at"] = now()
        row["version"] = 1
    return row


def touch(row):
    """A mutation: refresh updated_at and increment version by exactly 1."""
    row["updated_at"] = now()
    row["version"] = row["version"] + 1


def in_creation_order(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def all_rows(collection):
    return in_creation_order(getattr(db, collection).values())
