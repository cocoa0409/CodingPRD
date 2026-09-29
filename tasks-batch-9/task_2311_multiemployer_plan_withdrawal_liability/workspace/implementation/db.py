"""In-memory data store.

The store is empty on every boot.  Nothing is seeded, preloaded or hardcoded:
every entity is created through the declared API surface by the caller.
"""

import uuid
from datetime import datetime, timezone

# PRD §2.4 — before any client sets it, the logical clock reads exactly this.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "plans",
    "controlled_groups",
    "employers",
    "valuations",
    "contribution_records",
    "withdrawal_events",
    "assessments",
    "schedules",
    "installments",
    "review_requests",
    "arbitrations",
    "transactions",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = INITIAL_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())
