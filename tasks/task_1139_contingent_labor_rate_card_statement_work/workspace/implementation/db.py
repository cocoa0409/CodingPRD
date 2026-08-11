"""In-memory data store, logical clock, and id/timestamp helpers.

The store starts completely empty on every boot. No seeding anywhere.
All server-stamped timestamps read the logical clock (default
2026-05-01T00:00:00Z), never wall-clock time.
"""

import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.suppliers = {}
        self.rate_cards = {}
        self.engagements = {}
        self.offers = {}
        self.workers = {}
        self.assignments = {}
        self.timesheets = {}
        self.milestones = {}
        self.invoices = {}
        self.invoice_lines = {}
        self.conversion_requests = {}
        self.audits = {}
        self.ledger = {}
        self.seq = 0  # global insertion sequence for stable created_at tie-breaks

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()
_clock = {"now": DEFAULT_CLOCK}


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def today():
    return clock_now().astimezone(timezone.utc).date()


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-05-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_ts(clock_now())


def today_str():
    return today().isoformat()


def new_id():
    return str(uuid.uuid4())


def stamp_new(rec):
    """Assign id, created_at, updated_at, version=1 to a new common-fields record."""
    ts = now_iso()
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = store.next_seq()
    return rec


def stamp_new_light(rec):
    """InvoiceLine / SpendLedgerEntry: only id and created_at (immutable records)."""
    rec["id"] = new_id()
    rec["created_at"] = now_iso()
    rec["_seq"] = store.next_seq()
    return rec


def touch(rec):
    """Mutation stamp: bump updated_at and version."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
    return rec
