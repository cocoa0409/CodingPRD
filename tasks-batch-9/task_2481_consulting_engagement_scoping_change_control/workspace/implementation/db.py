"""In-memory data store, logical clock and row bookkeeping.

Storage is process-local Python dicts only. The store starts EMPTY on every
boot: nothing is seeded, preloaded or hardcoded here or anywhere else.
"""

import itertools
import uuid
from datetime import datetime, timezone

from flask import g

# PRD 2.6: before the first clock write the clock reads exactly this instant and
# never falls back to wall-clock time.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TABLES = (
    "clients",
    "consultants",
    "opportunities",
    "deliverables",
    "sows",
    "engagements",
    "change_requests",
    "time_entries",
    "quality_reviews",
    "risk_escalations",
    "satisfaction_assessments",
)


class Store:
    def __init__(self):
        for t in TABLES:
            setattr(self, t, {})
        self.clock = CLOCK_EPOCH
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        "%03dZ" % (dt.microsecond // 1000)
    )


def clock_now():
    return db.clock


def clock_stamp():
    return fmt_ts(db.clock)


def clock_date():
    return db.clock.astimezone(timezone.utc).date()


def new_id():
    return str(uuid.uuid4())


def _touched():
    if not hasattr(g, "touched_rows"):
        g.touched_rows = set()
    return g.touched_rows


def new_row(fields, common=True):
    """Create a row.  Common-field rows start at version 1.

    The row is marked as already touched for this request so that a cascade
    firing later in the same request does not push a freshly created row to
    version 2.
    """
    row = {"id": new_id(), "_seq": db.next_seq()}
    stamp = clock_stamp()
    row["created_at"] = stamp
    if common:
        row["updated_at"] = stamp
        row["version"] = 1
    row.update(fields)
    _touched().add(id(row))
    return row


def touch(row):
    """Refresh updated_at and increment version, at most once per request.

    PRD 2.9 requires every row a cascade touches to have its updated_at
    refreshed and its version incremented by 1 -- by 1 for the request, which is
    why repeated logical mutations of the same row inside one request advance
    the counter exactly once (see 3.7: "three rows are touched, so three
    counters advance").
    """
    if row is None:
        return row
    marker = id(row)
    seen = _touched()
    if marker in seen:
        return row
    seen.add(marker)
    if "updated_at" in row:
        row["updated_at"] = clock_stamp()
    if "version" in row:
        row["version"] = row["version"] + 1
    return row


def rows(table):
    """All rows of a table in creation order."""
    return sorted(getattr(db, table).values(), key=lambda r: (r["created_at"], r["_seq"]))
