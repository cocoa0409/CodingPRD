"""In-memory data store.

Storage is process-local Python dicts keyed by id.  The store is EMPTY on every
boot: nothing is seeded, preloaded or hardcoded.  Every record is created by a
client through the declared endpoints.
"""
import uuid
from datetime import datetime

from util import UTC

# PRD 2.5: before any caller has moved it, the logical clock reads exactly this.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store(object):
    def __init__(self):
        self.assets = {}
        self.test_plans = {}
        self.scope_items = {}
        self.engagements = {}
        self.roes = {}
        self.targets = {}
        self.testers = {}
        self.assignments = {}
        self.findings = {}
        self.alerts = {}
        self.remediations = {}
        self.retests = {}
        self.training = {}
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    @staticmethod
    def new_id():
        return str(uuid.uuid4())

    def now(self):
        """The logical programme clock (PRD 2.5)."""
        return self.clock


store = Store()
