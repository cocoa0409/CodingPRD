"""In-memory data store, logical clock and row bookkeeping.

Storage is process-memory only: plain dicts, nothing on disk.  Every collection
starts empty on boot; no entity is ever seeded here.
"""
import itertools
import uuid
from datetime import datetime, timezone, timedelta

UTC = timezone.utc
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "creators",
    "tax_profiles",
    "products",
    "content_items",
    "revenue_events",
    "appeals",
    "periods",
    "statements",
    "payouts",
    "investigations",
    "funds",
    "allocations",
    "ledger",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.now = CLOCK_START
        self._seq = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})
        # request-scoped set of row ids already version-bumped this request
        self._touched = set()

    # ------------------------------------------------------------------ clock
    def set_clock(self, instant):
        self.now = instant

    # ------------------------------------------------------------- row helpers
    def next_seq(self):
        return next(self._seq)

    def new_request(self):
        self._touched = set()

    def insert(self, coll_name, data, common_fields=True):
        coll = getattr(self, coll_name)
        rec = dict(data)
        rec["id"] = str(uuid.uuid4())
        rec["created_at"] = self.now
        if common_fields:
            rec["updated_at"] = self.now
            rec["version"] = 1
        rec["_seq"] = self.next_seq()
        coll[rec["id"]] = rec
        # A freshly created row is considered already written this request, so a
        # later hop in the same request does not push its version past 1.
        self._touched.add(rec["id"])
        return rec

    def touch(self, rec):
        """Refresh updated_at; bump version at most once per request per row."""
        if rec is None:
            return rec
        rec["updated_at"] = self.now
        if rec["id"] not in self._touched:
            self._touched.add(rec["id"])
            rec["version"] = rec.get("version", 1) + 1
        return rec

    # ------------------------------------------------------------- accessors
    def rows(self, coll_name):
        return list(getattr(self, coll_name).values())

    def get(self, coll_name, row_id):
        if not isinstance(row_id, str):
            return None
        return getattr(self, coll_name).get(row_id)


db = Store()


def now():
    return db.now


def days(n):
    return timedelta(days=n)


def iso(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def sort_rows(rows, keyfn):
    return sorted(rows, key=lambda r: tuple(keyfn(r)) + (r["_seq"],))
