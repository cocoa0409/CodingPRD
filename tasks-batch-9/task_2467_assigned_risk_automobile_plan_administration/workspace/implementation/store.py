"""In-memory data store and the logical plan clock.

The store starts completely empty on every boot: no entity is seeded, preloaded
or hardcoded.  Every row is created by a client through a declared endpoint.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

# PRD Section 2.5: before any call is made the clock reads exactly this instant.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

lock = threading.RLock()


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_EPOCH
        self.carriers = {}
        self.producers = {}
        self.applicants = {}
        self.vehicles = {}
        self.applications = {}
        self.market_rejections = {}
        self.plan_periods = {}
        self.assignment_cycles = {}
        self.assignments = {}
        self.policies = {}
        self.claims = {}
        self.complaints = {}
        self.reconciliations = {}
        self._insert_seq = 0
        self._enrollment_seq = 0
        self._intake_seq = 0

    def next_insert_seq(self):
        self._insert_seq += 1
        return self._insert_seq

    def next_enrollment_sequence(self):
        self._enrollment_seq += 1
        return self._enrollment_seq

    def next_intake_sequence(self):
        self._intake_seq += 1
        return self._intake_seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_row(versioned=True):
    """A fresh row carrying the audit fields of PRD Section 2.4."""
    row = {
        "id": new_id(),
        "created_at": db.clock,
        "_seq": db.next_insert_seq(),
    }
    if versioned:
        row["updated_at"] = db.clock
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and increment version on any mutation."""
    if row is None:
        return
    if "version" in row:
        row["updated_at"] = db.clock
        row["version"] = row["version"] + 1


def days(n):
    return timedelta(days=n)


def whole_days(later, earlier):
    """Whole (floored) days between two instants."""
    return (later - earlier) // timedelta(days=1)
