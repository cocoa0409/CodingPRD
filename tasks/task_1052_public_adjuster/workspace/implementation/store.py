"""In-memory data store and logical clock for the Public Adjuster API.

Everything lives in process memory. The store starts empty on every boot; no
entity is ever seeded. The logical clock defaults to 2026-07-01T00:00:00Z and
never falls back to wall-clock time.
"""

import uuid
from datetime import datetime, timezone

# Default logical-clock instant at server startup.
DEFAULT_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.adjusters = {}
        self.licenses = {}
        self.clients = {}
        self.policies = {}
        self.contracts = {}
        self.claims = {}
        self.supplements = {}
        self.appraisals = {}
        self.payments = {}
        self.disbursements = {}
        self.disputes = {}

        # Monotonic sequence for stable created_at ordering.
        self._seq = 0

        # Logical clock.
        self.clock = DEFAULT_CLOCK

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock

    def set_clock(self, dt):
        self.clock = dt


db = Store()


def new_id():
    return str(uuid.uuid4())
