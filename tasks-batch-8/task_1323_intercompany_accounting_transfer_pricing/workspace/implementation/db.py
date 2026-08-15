"""In-memory data store, logical clock, and resource helpers.

The store starts completely empty on every boot — no seeding of any kind.
"""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0  # monotonic creation sequence (== created_at ASC order)
        # Logical clock: reads exactly 2026-08-01T00:00:00Z before any set;
        # never falls back to wall-clock time (PRD 2.5).
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.fiscal_years = {}
        self.legal_entities = {}
        self.agreements = {}
        self.transactions = {}
        self.true_up_runs = {}
        self.studies = {}
        self.doc_packages = {}
        self.audit_cases = {}
        self.cash_pools = {}


store = Store()


def new_id():
    return str(uuid.uuid4())


def wall_now_iso():
    """Wall-clock UTC timestamp with three fractional digits (PRD 2.4)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def fmt_instant(dt):
    """Format a logical-clock instant: no fraction when zero, else 3-digit millis."""
    dt = dt.astimezone(timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        s += "." + f"{dt.microsecond // 1000:03d}"
    return s + "Z"


def clock_iso():
    return fmt_instant(store.clock)


def new_resource():
    store.seq += 1
    ts = wall_now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.seq,
    }


def touch(res):
    """PRD 2.4: every mutation increments version by exactly 1 and refreshes updated_at."""
    res["version"] += 1
    res["updated_at"] = wall_now_iso()


def public(res):
    """Strip internal underscore-prefixed keys (recursively) for output."""
    if isinstance(res, dict):
        return {k: public(v) for k, v in res.items()
                if not (isinstance(k, str) and k.startswith("_"))}
    if isinstance(res, list):
        return [public(v) for v in res]
    return res
