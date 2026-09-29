"""In-memory data store. Starts completely empty on every boot: no seeding."""

import itertools
import threading
import uuid
from datetime import datetime, timezone

# The logical season clock's default reading (PRD section 2.10).
DEFAULT_CLOCK_RAW = "2026-08-01T00:00:00.000Z"
DEFAULT_CLOCK_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_seq_counter = itertools.count(1)


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Server timestamp: ISO 8601 UTC with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.spaces = {}
        self.artists = {}
        self.clients = {}
        self.departments = {}
        self.equipment = {}
        self.engagements = {}
        self.negotiations = {}
        self.riders = {}
        self.lines = {}
        self.calls = {}
        self.tiers = {}
        self.sales = {}
        self.packages = {}
        self.settlements = {}
        self.programs = {}
        self.ledger = {}
        self.clock_raw = DEFAULT_CLOCK_RAW
        self.clock_dt = DEFAULT_CLOCK_DT


store = Store()


def stamp(rec):
    """Attach the common resource properties (PRD section 2.4)."""
    ts = now_iso()
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def stamp_ledger(rec):
    """ReserveLedgerEntry is append-only: only id and created_at."""
    rec["id"] = new_id()
    rec["created_at"] = now_iso()
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and increment version by exactly 1."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def touch_time_only(rec):
    """Refresh updated_at without advancing the version counter."""
    rec["updated_at"] = now_iso()
    return rec


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def ordered(records):
    """Default list ordering: created_at ascending (insertion sequence breaks ties)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
