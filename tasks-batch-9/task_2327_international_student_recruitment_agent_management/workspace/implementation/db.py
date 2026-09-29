"""In-memory data store and the server-controlled logical clock.

The store starts completely empty on every boot: no entity is seeded,
preloaded or hardcoded.  Every record any client needs is created through
the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.5 - the logical clock starts at this fixed default and never falls
# back to wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.agencies = {}
        self.programs = {}
        self.contracts = {}
        self.assignments = {}
        self.schedules = {}
        self.certifications = {}
        self.applications = {}
        self.documents = {}
        self.incidents = {}
        self.entries = {}
        self.scorecards = {}
        self.transitions = {}
        self.clock = DEFAULT_CLOCK
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_dt():
    return db.clock


def now_iso():
    return fmt_ts(db.clock)


def today():
    """Current logical-clock date."""
    return db.clock.astimezone(timezone.utc).date()


def base_record(with_version=True):
    ts = now_iso()
    rec = {"id": new_id(), "created_at": ts, "_seq": db.next_seq()}
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh a resource's own mutation bookkeeping (PRD 2.4)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def creation_order(records):
    """Default list ordering: created_at ascending, insertion order on ties."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
