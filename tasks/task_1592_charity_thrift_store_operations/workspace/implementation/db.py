"""In-memory data store + logical clock.

Storage is process-local dicts keyed by id. No persistence of any kind —
each start.sh re-invocation wipes every byte of state. Nothing is seeded.
"""
import uuid
from datetime import datetime, timezone


def _epoch_start():
    # PRD §2.5: before any client call the clock reads exactly 2026-08-01T00:00:00Z
    return datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = _epoch_start()

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


class DB:
    def __init__(self):
        self.clock = Clock()
        self.donors = {}
        self.batches = {}
        self.items = {}
        self.guidelines = {}
        self.vendors = {}
        self.bales = {}
        self.sales = {}
        self.till_sessions = {}
        self.routes = {}
        self.stops = {}
        self.workers = {}
        self.shifts = {}
        self.assignments = {}
        self.cycles = {}
        self.transfers = {}
        self.receipts = {}
        self.receipt_seq = 0
        self.cycle_seq = 0

    def next_receipt_number(self):
        self.receipt_seq += 1
        return "RCT-%06d" % self.receipt_seq

    def next_cycle_sequence(self):
        self.cycle_seq += 1
        return self.cycle_seq


db = DB()


def new_id():
    return str(uuid.uuid4())


def iso_now():
    return format_ts(db.clock.now())


def format_ts(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # ISO 8601 UTC with three fractional digits, trailing Z
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_ts(value):
    """Parse an ISO8601 timestamp (accepts trailing Z or numeric offset)."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def touch(record):
    """Bump version + updated_at on a mutated record (PRD §2.4)."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = iso_now()


def new_record():
    now = iso_now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
