"""In-memory data store and logical clock.

The store starts completely empty on every boot (per-test-server isolation).
No seeding of any kind happens here.
"""
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.employers = {}
        self.tpa_engagements = {}
        self.state_rules = {}
        self.separations = {}
        self.claims = {}
        self.responses = {}
        self.evidence = {}
        self.determinations = {}
        self.appeals = {}
        self.hearings = {}
        self.witnesses = {}
        self.charge_statements = {}
        self.charge_lines = {}
        self.charge_protests = {}
        self.rating_models = {}
        # Logical clock: server startup default is exactly 2026-08-01T00:00:00Z.
        # It NEVER falls back to wall-clock time.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_raw = "2026-08-01T00:00:00Z"
        self.seq = 0  # monotonic creation sequence (insertion order)

    def next_seq(self):
        self.seq += 1
        return self.seq


STORE = Store()
