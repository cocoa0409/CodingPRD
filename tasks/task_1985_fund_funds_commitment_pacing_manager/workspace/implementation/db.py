"""In-memory data store and the logical clock (PRD 2.7 / 2.9).

The store starts empty on every boot -- no seeding. The logical clock is
seeded at exactly 2026-08-01T00:00:00Z and never falls back to wall time.
"""

import threading
import uuid
from datetime import datetime, timezone

CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.programs = {}
        self.pacing_plans = {}
        self.managers = {}
        self.vehicles = {}
        self.dd_reviews = {}
        self.proposals = {}
        self.commitments = {}
        self.calls = {}
        self.distributions = {}
        self.ledger_entries = {}
        self.secondary_bids = {}
        self.snapshots = {}
        self.look_through_lines = {}
        self.valuation_reports = {}
        self.staff_users = {}
        self.seq = 0
        self.clock = CLOCK_START


STORE = Store()
LOCK = threading.RLock()


def next_seq():
    STORE.seq += 1
    return STORE.seq


def new_id():
    return str(uuid.uuid4())


def now():
    return STORE.clock


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(STORE.clock)


def new_entity(table, fields, common=True):
    """Create an entity. common=False -> id/created_at only (CashLedgerEntry,
    LookThroughLine, StaffUser carry no updated_at/version)."""
    e = dict(fields)
    e["id"] = new_id()
    e["_seq"] = next_seq()
    ts = now_iso()
    e["created_at"] = ts
    if common:
        e["updated_at"] = ts
        e["version"] = 1
    table[e["id"]] = e
    return e


def touch(e):
    """Every mutation advances updated_at and increments version by one."""
    e["version"] += 1
    e["updated_at"] = now_iso()


def public(e):
    """Serialize: strip internal underscore-prefixed bookkeeping fields."""
    return {k: v for k, v in e.items() if not k.startswith("_")}
