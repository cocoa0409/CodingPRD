"""In-memory data store and the server-maintained logical clock.

Storage is purely in-memory (dicts keyed by id). The process is relaunched
by the harness before every test, so every boot starts with empty state.
Nothing is seeded or preloaded here.
"""

from datetime import datetime, timezone

# Logical clock startup default mandated by the PRD: 2026-08-01T00:00:00Z.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.clock = CLOCK_DEFAULT
        self.counter = 0  # monotonic creation ordering tiebreak
        self.productions = {}
        self.sequences = {}
        self.assessments = {}
        self.performers = {}
        self.certifications = {}
        self.rehearsals = {}
        self.meetings = {}
        self.signoffs = {}
        self.equipment = {}
        self.inspections = {}
        self.permits = {}
        self.adjustments = {}
        self.incidents = {}
        self.executions = {}
        self.reviews = {}

    def now(self):
        return self.clock

    def set_clock(self, to_dt):
        self.clock = to_dt

    def next_seq(self):
        self.counter += 1
        return self.counter


store = Store()
