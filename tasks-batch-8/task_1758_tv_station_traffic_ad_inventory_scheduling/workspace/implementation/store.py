"""In-memory data store and logical clock.

The store starts completely empty on every boot — no seeding of any kind.
The logical clock starts at exactly 2026-08-01T00:00:00Z per PRD §2.5 and is
only ever advanced through POST /traffic/_clock/set_current_utc.
"""

import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Logical clock — never the real wall clock (PRD §2.5).
        self.now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Global monotonic creation counter: the fixed tie-break whenever
        # logical-clock creation timestamps compare equal (PRD §2.3, §3.5).
        self.seq = 0
        # Global write lock: serializes requests so OCC races resolve cleanly.
        self.lock = threading.RLock()
        # Entity tables, keyed by id.
        self.advertisers = {}
        self.programs = {}
        self.avail_weeks = {}
        self.avail_units = {}
        self.orders = {}
        self.order_lines = {}
        self.copy_instructions = {}
        self.spots = {}
        self.log_days = {}
        self.as_run_entries = {}
        # Discrepancy-credit ledger (append-only): one row per posted credit.
        self.credit_entries = []

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()
