"""In-memory data store. Fresh, empty state on every process boot (PRD: no seeding).

The logical clock starts at exactly 2026-08-01T00:00:00Z and moves only via
POST /coaching/_clock/set_current_utc (PRD §2.5). It never falls back to
wall-clock time.
"""
from datetime import datetime, timezone

INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.coaches = {}
        self.clients = {}
        self.tiers = {}
        self.discovery_calls = {}
        self.fit_assessments = {}
        self.enrollments = {}
        self.installments = {}
        self.sessions = {}
        self.goals = {}
        self.check_ins = {}
        self.cohorts = {}
        self.memberships = {}
        self.testimonials = {}
        self.refunds = {}
        self.clock = INITIAL_CLOCK
        self.seq = 0  # monotonic insertion counter (stable ordering tie-break)

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()
