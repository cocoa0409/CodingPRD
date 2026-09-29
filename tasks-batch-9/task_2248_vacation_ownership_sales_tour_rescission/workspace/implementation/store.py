"""In-memory data store and the logical clock.

Storage is process-memory only: plain Python dicts, no file, no database.
The store is created empty on every boot and is NEVER seeded or preloaded.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.5: the logical clock reads exactly 2026-08-01T00:00:00Z until first set.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "channels",
    "galleries",
    "reps",
    "prospects",
    "bookings",
    "presentations",
    "acknowledgments",
    "findings",
    "agreements",
    "financings",
    "rescissions",
    "refunds",
    "packages",
    "retrainings",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._seq = itertools.count(1)

    # -- identity / ordering ------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)

    # -- logical clock -----------------------------------------------------
    def now(self):
        return self.clock

    def set_clock(self, value):
        previous = self.clock
        self.clock = value
        return previous


db = Store()


def ordered(values):
    """Default list ordering: created_at ASC, insertion sequence as tie-break."""
    return sorted(values, key=lambda e: (e["created_at"], e["_seq"]))
