"""In-memory data store and logical clock.

Storage is process-local dictionaries keyed by id. Nothing is persisted and
nothing is seeded: every row is created by an API call.
"""

import itertools
import uuid
from datetime import datetime, timezone, date, timedelta

# Before any administrator moves it, the logical clock reads exactly this instant.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.vendors = {}
        self.integration_tests = {}
        self.items = {}
        self.rules = {}
        self.blackouts = {}
        self.snapshots = {}
        self.orders = {}
        self.lines = {}
        self.shipments = {}
        self.returns = {}
        self.scorecards = {}
        self.clock = DEFAULT_CLOCK
        self._counter = itertools.count(1)

    def seq(self):
        return next(self._counter)


db = Store()


def now():
    return db.clock


def set_clock(dt):
    db.clock = dt


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def iso_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.astimezone(timezone.utc).date()
    return d.isoformat()


def parse_dt(value):
    """Parse an ISO-8601 instant. Returns None when the value is unusable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a UTC calendar date in YYYY-MM-DD form."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if len(s) != 10:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def new_row(versioned=True):
    t = now()
    row = {"id": new_id(), "created_at": t, "_seq": db.seq()}
    if versioned:
        row["updated_at"] = t
        row["version"] = 1
    return row


def touch(row, bump=True):
    """Refresh updated_at to the logical clock and advance version by one."""
    row["updated_at"] = now()
    if bump and "version" in row:
        row["version"] = row["version"] + 1


def sort_created(rows):
    """created_at ascending, insertion order as the stable tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def days_between(a, b):
    return (a - b).days


def add_days(d, n):
    return d + timedelta(days=n)
