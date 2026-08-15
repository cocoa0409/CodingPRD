"""In-memory data store. All state lives here and is reset per process."""

import itertools
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.jobs = {}             # id -> PackOutJob dict
        self.rooms = {}            # id -> Room dict
        self.items = {}            # id -> Item dict
        self.disposal_records = {} # id -> DisposalRecord dict
        self.cleaning_tasks = {}   # id -> CleaningTask dict
        self.vaults = {}           # id -> Vault dict
        self.placements = {}       # id -> StoragePlacement dict
        self.subcontractors = {}   # id -> Subcontractor dict
        self.referrals = {}        # id -> SpecialtyReferral dict
        self.custody_events = {}   # id -> CustodyEvent dict
        self.claims = {}           # id -> HandlingClaim dict
        self.schedules = {}        # id -> PackBackSchedule dict
        self.statements = {}       # id -> StorageStatement dict
        self.invoices = {}         # id -> CarrierInvoice dict
        self._clock = datetime(2026, 8, 1, tzinfo=timezone.utc)
        self._req_counter = itertools.count(1)

    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt

    def now_iso(self):
        return format_iso(self._clock)

    def today_str(self):
        return self._clock.strftime("%Y-%m-%d")

    def next_req_id(self):
        n = next(self._req_counter)
        return f"req_{n:020d}"


def format_iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits, Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


store = Store()
