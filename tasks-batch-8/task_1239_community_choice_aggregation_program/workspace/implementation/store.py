"""In-memory data store and logical clock. Fresh per process boot."""

import uuid
from datetime import datetime, timezone

from util import fmt_dt

CLOCK_START = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.authorities = {}
        self.accounts = {}
        self.notices = {}
        self.opt_outs = {}
        self.products = {}
        self.schedules = {}
        self.contracts = {}
        self.forecasts = {}
        self.extracts = {}
        self.lines = {}
        self.remittances = {}
        self.pools = {}
        self.filings = {}
        self.recs = {}
        self.seq = 0
        self.clock_now = CLOCK_START

    def now(self):
        return self.clock_now

    def now_iso(self):
        return fmt_dt(self.clock_now)

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self.seq += 1
        return self.seq

    def new_record(self, with_version=True):
        """Common system fields for a freshly created record."""
        rec = {
            "id": self.new_id(),
            "created_at": self.now_iso(),
            "_created_dt": self.clock_now,
            "_seq": self.next_seq(),
        }
        if with_version:
            rec["updated_at"] = rec["created_at"]
            rec["_updated_dt"] = self.clock_now
            rec["version"] = 1
        return rec

    def touch(self, rec):
        """Refresh updated_at and bump version on a versioned record."""
        rec["updated_at"] = self.now_iso()
        rec["_updated_dt"] = self.clock_now
        rec["version"] = rec.get("version", 1) + 1

    def refresh_only(self, rec):
        """Refresh updated_at WITHOUT incrementing version (named cascade exception)."""
        rec["updated_at"] = self.now_iso()
        rec["_updated_dt"] = self.clock_now

    # -- singleton authority -------------------------------------------------
    def authority(self):
        for a in self.authorities.values():
            return a
        return None


STORE = Store()
