"""In-memory data store and logical clock."""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0
        # Logical clock: starts exactly at 2026-08-01T00:00:00Z, never wall-clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.funds = {}
        self.tax_years = {}
        self.partners = {}
        self.capital_events = {}
        self.transfers = {}
        self.allocation_runs = {}
        self.allocation_lines = {}
        self.special_allocations = {}
        self.composite_filings = {}
        self.withholding_records = {}
        self.k1_packages = {}
        self.k1_amendments = {}
        self.tickets = {}


db = Store()


def next_seq():
    db.seq += 1
    return db.seq


def now():
    return db.clock


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def new_entity():
    ts = fmt_ts(now())
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(ent):
    """Refresh updated_at and bump version (every modification, incl. cascades)."""
    ent["updated_at"] = fmt_ts(now())
    ent["version"] += 1
