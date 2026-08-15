"""In-memory data store and logical clock.

Storage is process-local only: plain dicts keyed by id. Every boot starts
empty; nothing is seeded, persisted, or cached anywhere on disk.
"""

import threading
from datetime import datetime, timezone

# Startup default per PRD 2.4: exactly 2026-08-01T00:00:00Z; never falls back
# to wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.clock = CLOCK_DEFAULT
        self.employees = {}
        self.candidates = {}
        self.requisitions = {}
        self.policies = {}
        self.campaigns = {}
        self.referrals = {}
        self.milestones = {}
        self.batches = {}
        self.abuse_cases = {}
        self.tax_profiles = {}  # keyed by employee_id (1:1 with Employee)
        self.events = {}        # ReferralEvent id -> event
        self.seq = 0            # global insertion sequence for stable ordering

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()

# Serializes request handling so concurrent requests cannot interleave
# multi-entity mutations.
lock = threading.RLock()
