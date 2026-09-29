"""In-memory data store and the server's logical clock.

The store starts completely empty on every boot.  Nothing is seeded, preloaded
or hardcoded — every row is created by a caller through the declared API.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: on start-up the logical clock reads exactly 2026-08-01T00:00:00Z.
CLOCK_EPOCH_RAW = "2026-08-01T00:00:00Z"
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def iso_ms(dt):
    """Canonical ISO-8601 UTC rendering with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_iso(value):
    """Parse an ISO-8601 timestamp, returning an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.facilities = {}
        self.departments = {}
        self.cycles = {}
        self.allocations = {}
        self.assets = {}
        self.service_events = {}
        self.requests = {}
        self.scores = {}
        self.members = {}
        self.votes = {}
        self.contracts = {}
        self.quotes = {}
        self.projects = {}
        self.audits = {}

        self.clock = CLOCK_EPOCH
        self.clock_raw = CLOCK_EPOCH_RAW

        self._seq = 0
        self._last_ts = None

    # -- identity / ordering helpers -------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())

    def wall_now(self):
        """Monotonically non-decreasing wall-clock instant for created_at."""
        now = datetime.now(timezone.utc)
        if self._last_ts is not None and now <= self._last_ts:
            now = self._last_ts + timedelta(microseconds=1000)
        self._last_ts = now
        return now

    def stamp(self):
        return iso_ms(self.wall_now())

    def now(self):
        """The logical clock instant."""
        return self.clock


db = Store()


def new_row(extra=None):
    """A fresh row carrying the common system fields."""
    ts = db.stamp()
    row = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def new_child_row(extra=None):
    """A fresh row for entities that only carry id and created_at."""
    row = {
        "id": db.new_id(),
        "created_at": db.stamp(),
        "_seq": db.next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def touch(row):
    """Record a mutation: bump the version and refresh updated_at."""
    row["version"] = row.get("version", 0) + 1
    row["updated_at"] = db.stamp()
    return row


def ordered(rows):
    """created_at ascending, with insertion order as the stable tie-break."""
    return sorted(rows, key=lambda r: r["_seq"])
