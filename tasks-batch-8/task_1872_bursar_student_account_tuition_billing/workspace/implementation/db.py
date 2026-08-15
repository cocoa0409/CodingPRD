"""In-memory data store and logical clock.

The store starts empty on every boot. No entity is ever seeded, preloaded,
or hardcoded at startup; all entities are constructed via the declared API.
"""
import uuid
from datetime import datetime, timezone, timedelta


class Store:
    def __init__(self):
        self.terms = {}
        self.students = {}
        self.rates = {}
        self.accounts = {}
        self.ledger_entries = {}
        self.enrollments = {}
        self.payments = {}
        self.waivers = {}
        self.agreements = {}
        self.invoices = {}
        self.plans = {}
        self.installments = {}
        self.holds = {}
        self.refunds = {}
        self.tax_forms = {}
        self.seq = 0
        # Logical clock: server startup default is exactly 2026-08-01T00:00:00Z
        # and never falls back to wall-clock time.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.last_ts = None


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def fmt_ts(dt):
    """ISO 8601 UTC timestamp with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Wall-clock timestamp for created_at/updated_at/meta; strictly increasing."""
    now = datetime.now(timezone.utc)
    now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
    if store.last_ts is not None and now <= store.last_ts:
        now = store.last_ts + timedelta(milliseconds=1)
    store.last_ts = now
    return fmt_ts(now)


def fmt_clock(dt):
    """Format the logical clock instant."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_date():
    """Current date per the logical clock."""
    return store.clock.date()


def base_fields():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": next_seq()}


def touch(record):
    record["version"] += 1
    record["updated_at"] = now_iso()
