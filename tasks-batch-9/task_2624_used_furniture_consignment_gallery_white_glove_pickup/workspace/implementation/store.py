"""In-memory data store, logical clock and row helpers.

Storage is plain Python dicts held in module state. Nothing is persisted and
nothing is ever seeded: every row is created through a declared endpoint.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

SECONDS_PER_DAY = 86400

# PRD 2.5: before any client has set it, the clock reads exactly this instant
# and never falls back to the host's wall clock.
CLOCK_ORIGIN = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_COLLECTIONS = (
    "consignors",
    "buyers",
    "price_schedules",
    "price_schedule_steps",
    "agreements",
    "items",
    "trucks",
    "crews",
    "zones",
    "pickup_jobs",
    "sales",
    "delivery_orders",
    "damage_claims",
    "shrinkage_audits",
    "ledger_entries",
)


class Store(object):
    def __init__(self):
        self.clock = CLOCK_ORIGIN
        self._seq = itertools.count(1)
        for name in _COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """The logical clock reading."""
    return db.clock


def set_clock(value):
    db.clock = value


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO-8601 instant. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(seconds=int(days) * SECONDS_PER_DAY)


def add_seconds(dt, seconds):
    return dt + timedelta(seconds=int(seconds))


def whole_days_between(start, end):
    """floor((end - start) / 86400); never negative-rounded oddly."""
    if start is None or end is None:
        return 0
    elapsed = int((end - start).total_seconds())
    if elapsed <= 0:
        return 0
    return elapsed // SECONDS_PER_DAY


def new_row(collection, fields, versioned=True):
    """Insert a row with the common fields of PRD 2.4."""
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = now()
    row["_seq"] = db.next_seq()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    collection[row["id"]] = row
    return row


def touch(row):
    """Register a real mutation: bump version and refresh updated_at."""
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = now()
    return row


def ordered(collection, key=None):
    """Rows in created_at ascending order (insertion order breaks ties)."""
    rows = list(collection.values())
    if key is None:
        key = lambda r: (r["created_at"], r["_seq"])
    rows.sort(key=key)
    return rows


def by_created_at(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
