"""In-memory data store and logical clock.

The store starts completely empty on every boot — no seeding of any kind.
Every entity is created exclusively through the declared API surface.
"""
import threading
from datetime import datetime, timezone

# Logical clock default per PRD section 2.5: 2026-08-01T00:00:00Z.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = DEFAULT_CLOCK
        self.seq = 0       # global monotonic insertion sequence (tie-breaks sorts)
        self.mrn_seq = 0   # MRN minting sequence
        self.patients = {}
        self.policies = {}
        self.eligibility_checks = {}
        self.referrals = {}
        self.authorizations = {}
        self.appointments = {}
        self.estimates = {}
        self.payments = {}
        self.tickets = {}
        self.flags = {}

    def next_seq(self):
        self.seq += 1
        return self.seq

    def next_mrn(self):
        self.mrn_seq += 1
        return "MRN" + "%08d" % self.mrn_seq


db = Store()
