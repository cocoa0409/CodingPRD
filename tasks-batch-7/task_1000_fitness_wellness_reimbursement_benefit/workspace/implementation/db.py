"""In-memory data store and logical clock.

The store starts completely empty on every boot (per-test-server isolation).
No seeding of any kind happens here.
"""
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.employers = {}
        self.plans = {}
        self.tiers = {}            # tier_id -> tier dict
        self.members = {}
        self.dependents = {}
        self.providers = {}
        self.enrollments = {}
        self.visits = {}
        self.claims = {}
        self.funding_accounts = {}
        self.funding_entries = {}
        self.fraud_flags = {}
        self.statements = {}
        # Logical clock: server startup default is exactly 2026-05-01T00:00:00Z.
        # It NEVER falls back to wall-clock time.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_raw = "2026-05-01T00:00:00Z"
        self.seq = 0               # monotonic creation sequence (insertion order)

    def next_seq(self):
        self.seq += 1
        return self.seq


STORE = Store()
