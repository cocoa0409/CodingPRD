"""In-memory data store and the server-held logical UTC clock.

The store is EMPTY on every boot.  Nothing is seeded, preloaded or hardcoded;
all entities arrive exclusively through the declared HTTP endpoints.
"""

import uuid
from datetime import datetime, timezone

# PRD §2.4 — before the clock has ever been set it reads exactly this instant,
# and it never falls back to real wall-clock time.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.facilities = {}
        self.clinicians = {}
        self.patients = {}
        self.screenings = {}
        self.admissions = {}
        self.plans = {}
        self.weeks = {}
        self.sessions = {}
        self.conferences = {}
        self.assessments = {}
        self.reviews = {}
        self.qrps = {}
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    @staticmethod
    def new_id():
        return str(uuid.uuid4())


store = Store()
