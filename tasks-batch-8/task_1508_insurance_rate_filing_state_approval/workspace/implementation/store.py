"""In-memory data store and logical clock.

The store starts completely empty on every boot — no seeding, no preloading.
The logical clock starts at exactly 2026-08-01T00:00:00Z and never consults
wall-clock time; it advances only via POST /_clock/set_current_utc.
"""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.products = {}
        self.state_profiles = {}
        self.rate_indications = {}
        self.rate_filings = {}
        self.filing_components = {}
        self.deviations = {}
        self.objections = {}
        self.objection_responses = {}
        self.implementation_waves = {}
        self.renewal_policies = {}
        self.compliance_calendar_entries = {}
        # per-state filing number sequence (state_code -> last issued int)
        self.filing_seq_by_state = {}
        # monotonic insertion counter used for stable created_at tie-breaking
        self.seq = 0
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.lock = threading.RLock()

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return db.clock


def touch(entity):
    """Every mutation refreshes updated_at and increments version."""
    entity["updated_at"] = db.clock
    entity["version"] += 1
