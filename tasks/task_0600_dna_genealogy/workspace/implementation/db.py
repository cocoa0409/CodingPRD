"""In-memory data store and the logical clock (PRD §2.4).

The store starts EMPTY on every boot. Nothing is seeded here.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

CLOCK_EPOCH = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

_seq = itertools.count(1)


class Store:
    def __init__(self):
        self.customers = {}
        self.subscriptions = {}
        self.kits = {}
        self.samples = {}
        self.instruments = {}
        self.batches = {}
        self.grants = {}
        self.reports = {}
        self.matches = {}
        self.trees = {}
        self.persons = {}
        self.hints = {}
        self.data_requests = {}
        self.clock = CLOCK_EPOCH
        self.barcode_counter = itertools.count(1)


db = Store()


def now():
    """The logical clock instant. Never wall-clock time."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 string into an aware UTC datetime, or return None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days(n):
    return timedelta(days=n)


def hours(n):
    return timedelta(hours=n)


def new_record(extra=None):
    """Common resource properties: id / created_at / updated_at / version."""
    t = now()
    rec = {
        "id": new_id(),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": next_seq(),
    }
    if extra:
        rec.update(extra)
    return rec


def touch(rec):
    """Mutation stamp: refresh updated_at and advance version by exactly 1."""
    rec["updated_at"] = now()
    rec["version"] = rec["version"] + 1
    return rec


def mint_barcode():
    n = next(db.barcode_counter)
    return "BC%s%06d" % (uuid.uuid4().hex[:10].upper(), n)


def by_creation(records):
    """Default list ordering: created_at ASC, stable on insertion order."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
