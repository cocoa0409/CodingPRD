"""In-memory data store, identity minting and the logical clock.

Storage is process-local Python dicts only.  Nothing is persisted, nothing is
seeded: every collection starts empty on every boot.
"""
import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.4 — the logical clock's default value.
CLOCK_DEFAULT_RAW = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def format_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.seasons = {}
        self.venues = {}
        self.bookings = {}
        self.stops = {}
        self.competitors = {}
        self.entries = {}
        self.inspections = {}
        self.segments = {}
        self.tiers = {}
        self.orders = {}
        self.sponsors = {}
        self.activations = {}
        self.plans = {}
        self.allocations = {}
        self.settlements = {}
        self._seq = itertools.count(1)
        self.clock_dt = CLOCK_DEFAULT_DT
        self.clock_raw = CLOCK_DEFAULT_RAW

    def next_seq(self):
        return next(self._seq)


db = Store()


def now_iso():
    """Wall-clock stamp used for created_at / updated_at / api_request_timestamp."""
    return format_ts(datetime.now(timezone.utc))


def clock_raw():
    """The logical clock value, used for every server-stamped domain timestamp."""
    return db.clock_raw


def clock_dt():
    return db.clock_dt


def set_clock(raw, dt):
    db.clock_raw = raw
    db.clock_dt = dt


def new_id():
    return str(uuid.uuid4())


def new_row(**fields):
    ts = now_iso()
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def new_bare_row(**fields):
    """A row that carries only id + created_at (TechInspection)."""
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = now_iso()
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Bump the row's concurrency field and modification stamp."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1
    return row


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
