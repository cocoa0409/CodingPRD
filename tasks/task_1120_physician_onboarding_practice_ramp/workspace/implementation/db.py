"""In-memory data store and logical clock.

The store starts completely empty on every boot — no seeding of any kind.
Every entity is constructed through the declared API surface.
"""

import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0  # monotonic insertion sequence for stable created_at ordering
        # Logical clock: startup default is exactly 2026-05-01T00:00:00Z and it
        # never falls back to wall-clock time.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

        self.physicians = {}
        self.cases = {}
        self.offers = {}
        self.credential_items = {}
        self.training_plans = {}
        self.training_modules = {}
        self.schedule_templates = {}
        self.panels = {}
        self.campaigns = {}
        self.events = {}
        self.guarantees = {}
        self.milestones = {}
        self.assignments = {}
        self.checkins = {}
        self.snapshots = {}


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def wall_now():
    return datetime.now(timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC timestamp with three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.astimezone(timezone.utc).microsecond // 1000:03d}Z"


def now_ts():
    return fmt_ts(wall_now())


def clock_ts():
    """Domain timestamps (created_at / updated_at) read the logical clock —
    time in this domain is not wall-clock time (PRD section 2.4)."""
    return fmt_ts(store.clock)


def fmt_clock(dt):
    """Canonical ISO 8601 UTC for the logical clock (seconds precision unless
    sub-second data was supplied)."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f").rstrip("0") + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def new_record():
    """Common system-managed fields for primary resources."""
    ts = clock_ts()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def new_point_record():
    """CheckIn / RetentionRiskSnapshot carry only id + created_at."""
    return {
        "id": new_id(),
        "created_at": clock_ts(),
        "_seq": next_seq(),
    }


def bump(rec):
    """Every mutation refreshes updated_at and increments version."""
    rec["version"] += 1
    rec["updated_at"] = clock_ts()
