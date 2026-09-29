"""In-memory data store, logical clock and row bookkeeping.

The store starts completely EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded here: every entity is created by a client through the declared API.
"""

import itertools
import threading
import uuid
from datetime import datetime, timezone

from flask import g

# The logical clock's startup value (PRD §2.5).
LOGICAL_CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

REQUEST_LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.builders = {}
        self.subdivisions = {}
        self.plan_models = {}
        self.homes = {}
        self.raters = {}
        self.ratings = {}
        self.inspections = {}
        self.diagnostic_tests = {}
        self.sample_sets = {}
        self.qa_reviews = {}
        self.corrective_actions = {}
        self.document_packages = {}
        self.logical_clock = LOGICAL_CLOCK_DEFAULT
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


def new_id():
    return str(uuid.uuid4())


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now():
    return datetime.now(timezone.utc)


def wall_now_iso():
    return iso_ms(wall_now())


def clock_now():
    return db.logical_clock


def clock_now_iso():
    return iso_ms(db.logical_clock)


def new_row(kind, fields, versioned=True):
    """Create a row with the common resource properties (PRD §2.4)."""
    row = {"id": new_id(), **fields}
    row["created_at"] = wall_now_iso()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_type"] = kind
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Refresh updated_at and bump version — at most once per row per request."""
    if row is None or "version" not in row:
        return
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    key = (row.get("_type"), row.get("id"))
    if key in touched:
        return
    touched.add(key)
    row["version"] += 1
    row["updated_at"] = wall_now_iso()


def ordered(rows):
    """Default list ordering: created_at ascending (PRD §2.3)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
