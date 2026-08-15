"""In-memory data store and logical clock.

Storage is process-local only: plain dicts keyed by id. The store starts
empty on every boot; nothing is seeded. All time-dependent behavior reads
the logical clock (store.clock), never wall-clock time.
"""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.jurisdictions = {}
        self.scripts = {}
        self.resources = {}
        self.counselors = {}
        self.interpreters = {}
        self.callers = {}
        self.consents = {}
        self.sessions = {}
        self.cases = {}
        self.notes = {}
        self.follow_ups = {}
        self.orgs = {}
        self.referrals = {}
        self.policies = {}
        self.purge_jobs = {}
        # monotonic insertion sequence for stable created_at tie-breaking
        self.seq = 0
        # logical clock; startup default is exactly 2026-08-01T00:00:00Z
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def now():
    """Current logical time (timezone-aware UTC datetime)."""
    return store.clock
