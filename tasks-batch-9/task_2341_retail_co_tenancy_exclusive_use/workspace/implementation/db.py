"""In-memory store.

Every collection starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded — tests construct all state through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.4: a fresh instance starts its logical clock at this instant.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.centers = {}
        self.tenants = {}
        self.leases = {}
        self.conditions = {}
        self.anchor_requirements = {}
        self.clauses = {}
        self.restrictions = {}
        self.notices = {}
        self.disputes = {}
        self.elections = {}
        self.measurements = {}
        self.certificates = {}
        self.plans = {}
        self.clock = CLOCK_START
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


store = Store()


def new_id():
    """Server-minted UUID, no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())
