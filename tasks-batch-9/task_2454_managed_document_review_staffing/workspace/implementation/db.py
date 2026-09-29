"""In-memory data store and the server-wide logical clock.

The store starts completely empty on every boot: nothing is seeded, preloaded or
hardcoded.  Every row in here is created by a client through a declared endpoint.
"""

import itertools
import threading
import uuid
from datetime import datetime, timezone

# PRD 2.4 - the logical clock reads exactly this at startup and never falls back
# to wall-clock time.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK_START_RAW = "2026-08-01T00:00:00.000Z"


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.clients = {}
        self.matters = {}
        self.protocols = {}
        self.reviewers = {}
        self.screenings = {}
        self.agreements = {}
        self.sessions = {}
        self.batches = {}
        self.assignments = {}
        self.qc_samples = {}
        self.privilege_entries = {}
        self.scorecard_events = {}
        self.ledger_entries = {}
        self._seq = itertools.count(1)
        self.clock = CLOCK_START
        self.clock_raw = CLOCK_START_RAW

    def next_seq(self):
        return next(self._seq)

    # ---- logical clock -------------------------------------------------
    def now(self):
        return self.clock

    def now_iso(self):
        return fmt_ts(self.clock)

    def set_clock(self, dt, raw):
        self.clock = dt
        self.clock_raw = raw


db = Store()


def base_row():
    """The four system-managed properties shared by the eleven main entities."""
    stamp = db.now_iso()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def audit_row():
    """Append-only rows carry only id + created_at (PRD 2.6)."""
    return {
        "id": new_id(),
        "created_at": db.now_iso(),
        "_seq": db.next_seq(),
    }


def touch(row):
    """Mutation bookkeeping: refresh updated_at, increment version by one."""
    row["updated_at"] = db.now_iso()
    row["version"] = row["version"] + 1
    return row


def by_creation(rows):
    """created_at ascending; insertion sequence resolves same-instant ties."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def public(row, fields):
    return {name: row.get(name) for name in fields}
