"""In-memory data store. Starts completely empty on every boot — no seeding.

The logical clock is frozen at the last value set through
POST /_clock/set_current_utc (default 2026-08-01T00:00:00Z) so that
time-gated rules are deterministic.
"""

import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.plants = {}
        self.cylinders = {}
        self.preservatives = {}
        self.customers = {}
        self.charges = {}
        self.pieces = {}
        self.cycles = {}
        self.assays = {}
        self.inspections = {}
        self.drip_logs = {}
        self.warranties = {}
        self.slots = {}
        self.seq = 0
        self.clock = DEFAULT_CLOCK


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def now_iso():
    return fmt_ts(store.clock)


def new_entity(with_version=True):
    """Common system-managed properties (PRD section 2.4)."""
    e = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
    }
    if with_version:
        e["updated_at"] = e["created_at"]
        e["version"] = 1
    return e


def touch(e):
    """Record a mutation: refresh updated_at and advance version."""
    if "version" in e:
        e["version"] += 1
    if "updated_at" in e:
        e["updated_at"] = now_iso()


def public(e):
    """Strip internal bookkeeping fields for serialization."""
    return {k: v for k, v in e.items() if not k.startswith("_")}
