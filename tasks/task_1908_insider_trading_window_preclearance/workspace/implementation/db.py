"""In-memory data store and logical clock.

The store starts completely empty on every boot (per-test-server isolation).
No seeding of any kind happens here. All state lives in module-level dicts
keyed by id; every start.sh re-invocation wipes everything.
"""
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.covered_persons = {}
        self.deals = {}
        self.restricted_entries = {}
        self.blackout_windows = {}
        self.preclearance_requests = {}
        self.exception_requests = {}
        self.tenb5_plans = {}
        self.trade_confirmations = {}
        self.violation_cases = {}
        self.attestations = {}
        # Logical clock: default before any client call is exactly
        # 2026-08-01T00:00:00Z. The server NEVER falls back to wall-clock time.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0  # monotonic creation sequence (stable tiebreak for created_at)

    def next_seq(self):
        self.seq += 1
        return self.seq


STORE = Store()
