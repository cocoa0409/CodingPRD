"""In-memory data store, logical clock, and record helpers.

The store starts completely empty on every boot; nothing is seeded.
"""

import threading
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0  # global insertion sequence for stable created_at ordering
        self.clock = DEFAULT_CLOCK
        self.jobs = {}
        self.drawings = {}
        self.mill_orders = {}
        self.sequences = {}
        self.pieces = {}
        self.welders = {}
        self.welds = {}
        self.inspections = {}
        self.loads = {}
        self.fixes = {}
        self.backcharges = {}
        self.billings = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def new_record():
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(rec):
    """Every modification refreshes updated_at and increments version (PRD 2.4)."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def public(rec):
    """Strip internal keys before serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sorted_records(records):
    """Default list ordering: created_at ascending (insertion order breaks ties)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
