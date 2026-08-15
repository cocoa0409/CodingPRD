"""In-memory data store, logical clock, and timestamp/id helpers.

The store starts completely empty on every boot; every entity is created
through the declared API surface.
"""

import threading
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK_STR = "2026-08-01T00:00:00Z"


def now_ts():
    """Wall-clock UTC timestamp with three fractional digits (for created_at etc.)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def parse_iso_dt(s):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    v = s.strip()
    if v.endswith("Z") or v.endswith("z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Store:
    def __init__(self):
        self.sites = {}
        self.vendors = {}
        self.contracts = {}
        self.tickets = {}
        self.audits = {}
        self.events = {}
        self.goals = {}
        self.periods = {}
        self.applications = {}
        self.seq = 0
        self.clock_dt = parse_iso_dt(DEFAULT_CLOCK_STR)
        self.clock_str = DEFAULT_CLOCK_STR

    def next_seq(self):
        self.seq += 1
        return self.seq

    def clock_date(self):
        """The logical clock's date as an ISO date string (YYYY-MM-DD)."""
        return self.clock_dt.strftime("%Y-%m-%d")


store = Store()

# Global reentrant lock serializing all request handling (the Flask dev server
# runs threaded; atomicity matters for OCC checks).
lock = threading.RLock()


def base_record(extra):
    """Common system fields for a mutable resource."""
    ts = now_ts()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    rec.update(extra)
    return rec


def touch(rec):
    """Register a mutation: refresh updated_at and bump version."""
    rec["updated_at"] = now_ts()
    rec["version"] += 1
