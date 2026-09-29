"""In-memory data store, logical clock and audit-field helpers.

Storage is process-local Python dicts only. The store starts completely empty on
every boot; no entity is ever seeded, preloaded or hardcoded.
"""
import threading
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: until the clock is moved the logical now is 2026-08-01T00:00:00Z.
LOGICAL_CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.models = {}
        self.dealers = {}
        self.jigs = {}
        self.lanes = {}
        self.units = {}
        self.reservations = {}
        self.inspections = {}
        self.options = {}
        self.road_tests = {}
        self.labels = {}
        self.orders = {}
        self.claims = {}
        self.vin_counter = 0
        self.now = LOGICAL_CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def clock_now():
    return db.now


def now_iso():
    return fmt_dt(db.now)


def wall_now_iso():
    return fmt_dt(datetime.now(timezone.utc))


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def _touched_set():
    from flask import g
    seen = getattr(g, "_touched_rows", None)
    if seen is None:
        seen = set()
        g._touched_rows = seen
    return seen


def touch(row):
    """PRD 2.5 / 2.10: any hop that touches a row refreshes updated_at and
    increments version.  A row touched several times inside one request moves
    exactly once."""
    if row is None:
        return row
    seen = _touched_set()
    key = row.get("id")
    if key in seen:
        return row
    seen.add(key)
    row["version"] = int(row.get("version") or 0) + 1
    row["updated_at"] = now_iso()
    return row


def stamp_new(row):
    """Fill the common audit fields of a freshly created row."""
    ts = now_iso()
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    row["_seq"] = db.next_seq()
    _touched_set().add(row.get("id"))
    return row


def stamp_immutable(row):
    """FrameInspection: only id and created_at, no updated_at and no version."""
    row["created_at"] = now_iso()
    row["_seq"] = db.next_seq()
    return row


def public(row):
    if row is None:
        return None
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))


def public_list(rows):
    return [public(r) for r in rows]
