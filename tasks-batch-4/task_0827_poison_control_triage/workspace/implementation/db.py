"""In-memory data store and logical clock.

State is process-global and starts EMPTY on every boot. No seeding, no
persistence. The test harness restarts this server before every test, which
wipes all state.
"""
from datetime import datetime, timezone, timedelta
import itertools
import uuid

# Default logical clock: 2026-03-01T00:00:00Z (PRD §2.5)
DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.substances = {}
        self.facilities = {}
        self.protocols = {}
        self.specialists = {}
        self.cases = {}
        self.exposures = {}
        self.risk_assessments = {}
        self.dispositions = {}
        self.follow_up_calls = {}
        self.facility_consults = {}
        self.npds_reports = {}
        self.case_notes = {}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def now(self):
        return self.clock


db = Store()


def new_id():
    return str(uuid.uuid4())
