"""In-memory data store, logical clock, record helpers.

The store starts EMPTY on every boot — no seeding. All entity state is built
through the declared API surface. All timestamps are stamped from the logical
clock (default 2026-05-01T00:00:00Z), never wall-clock time.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal


class Store:
    def __init__(self):
        self.reps = {}
        self.customers = {}
        self.accounts = {}
        self.documents = {}
        self.certifications = {}
        self.owners = {}
        self.edd_reviews = {}
        self.transactions = {}
        self.rules = {}
        self.alerts = {}
        self.cases = {}
        self.sar_filings = {}
        self.fincen_requests = {}
        self.matches = {}
        self.deposits = {}
        self.lost_stolen = {}
        self.engagements = {}
        self.findings = {}
        self.seq = 0  # monotonic insertion counter (stable created_at tie-break)
        # Logical clock: startup default is exactly 2026-05-01T00:00:00Z.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_dt():
    return store.clock


def now_iso():
    return fmt_ts(store.clock)


def today():
    return store.clock.date()


def new_record():
    """Common fields: id, created_at, updated_at, version (starts at 1)."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": next_seq(),
    }


def bump(rec):
    rec["version"] += 1
    rec["updated_at"] = now_iso()


def serialize(rec):
    """Deep-copy a record for JSON output: drop internals, Decimal -> number."""
    if isinstance(rec, dict):
        out = {}
        for k, v in rec.items():
            if k.startswith("_"):
                continue
            out[k] = serialize(v)
        return out
    if isinstance(rec, list):
        return [serialize(v) for v in rec]
    if isinstance(rec, Decimal):
        return float(rec)
    return rec


def sorted_records(records):
    """List endpoints sort by created_at ascending; _seq breaks same-clock ties."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
