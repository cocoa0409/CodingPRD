"""In-memory data store and the logical clock.

The store starts empty on every boot — no seeding. All date-sensitive logic
reads the logical clock (default 2026-05-01T00:00:00Z), never wall-clock time.
"""
import threading
import uuid
from datetime import datetime, timezone

lock = threading.RLock()

# Logical clock — startup default exactly 2026-05-01T00:00:00Z
_clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def clock_now():
    return _clock


def set_clock(dt):
    global _clock
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _clock = dt.astimezone(timezone.utc)


def clock_date():
    return _clock.date()


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-05-01T00:00:00.000Z"""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_ts():
    return fmt_ts(_clock)


class Store:
    def __init__(self):
        self.districts = {}
        self.school_sites = {}
        self.bid_specs = {}
        self.spec_lines = {}
        self.coop_agreements = {}
        self.awards = {}
        self.purchase_orders = {}
        self.po_lines = {}
        self.shipments = {}
        self.crews = {}
        self.install_tasks = {}
        self.damage_reports = {}
        self.backorder_notices = {}
        self.warranty_claims = {}
        self.seq = 0  # global insertion counter (creation-order tiebreak)


store = Store()


def new_record(fields):
    """Create a record dict with the common system fields."""
    store.seq += 1
    ts = now_ts()
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.seq,
    }
    rec.update(fields)
    return rec


def touch(rec):
    """Mark a record mutated: bump version and refresh updated_at."""
    rec["version"] += 1
    rec["updated_at"] = now_ts()


def public(rec):
    """Strip internal (underscore-prefixed) fields for serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
