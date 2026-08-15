"""In-memory data store + logical clock.

All state lives in module-level dicts keyed by id. Nothing is persisted to
disk; every fresh process boot starts empty. The logical clock starts at
exactly 2026-08-01T00:00:00Z and is only moved by POST /_clock/set-current-utc.
"""

from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


class Store:
    def __init__(self):
        self.applicants = {}
        self.records_requests = {}
        self.equipment = {}
        self.training_classes = {}
        self.enrollments = {}
        self.training_events = {}
        self.checkrides = {}
        self.qualifications = {}
        self.flight_activities = {}
        self.medical_certificates = {}
        self.bid_periods = {}
        self.bids = {}
        self.instructors = {}
        self.simulator_slots = {}
        self.cost_ledger = {}
        # Monotonic insertion sequence, used as a stable tie-break for
        # created_at-ordered lists when several rows share one logical tick.
        self.seq = 0
        # Logical clock (timezone-aware UTC datetime).
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self.seq += 1
        return self.seq

    def now(self):
        return self.clock

    def set_clock(self, dt):
        self.clock = dt


# Single process-wide store. A fresh server process => a fresh Store.
store = Store()
