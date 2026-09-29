"""In-memory data store and the logical clock.

Storage is process-local Python dicts only. Nothing is persisted to disk, so a
fresh process (every `bash start.sh`) starts with a completely empty store and a
logical clock parked at the PRD's startup instant. No entity data is ever seeded
here: every row is built by callers through the declared endpoints.
"""

import itertools
import threading
import uuid
from datetime import datetime, timezone

# PRD 2.5: the logical clock's startup value is exactly this instant.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.venues = {}
        self.profiles = {}
        self.tenants = {}
        self.bookings = {}
        self.challenges = {}
        self.orders = {}
        self.ice_sheets = {}
        self.docks = {}
        self.labor_calls = {}
        self.assets = {}
        self.issues = {}
        self.clock = CLOCK_START
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def now_logical():
    """The logical clock instant that every temporal rule reads (PRD 2.5)."""
    return db.clock


def set_clock(instant):
    db.clock = instant


def new_id():
    return str(uuid.uuid4())


def wall_now():
    return datetime.now(timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def stamp_new(row, with_version=True):
    """Attach the common resource properties of PRD 2.4."""
    row["id"] = new_id()
    created = wall_now()
    row["created_at"] = created
    row["_seq"] = db.next_seq()
    if with_version:
        row["updated_at"] = created
        row["version"] = 1
    return row


def touch(row):
    """Record an accepted mutation of a row: refresh updated_at, bump version."""
    row["updated_at"] = wall_now()
    row["version"] = int(row.get("version", 1)) + 1
    return row


def ordered(rows):
    """Default list order: created_at ascending, insertion order as tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
