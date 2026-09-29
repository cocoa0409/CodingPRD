"""In-memory data store, logical clock and row mutation helpers.

Storage is process-local Python dicts only.  Nothing is seeded at import time or
at startup: every entity is created by clients through the declared endpoints.
"""
import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.4 — the logical clock's startup value is exactly 2026-08-01T00:00:00Z.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.programs = {}
        self.protocol_versions = {}
        self.rollouts = {}
        self.dispatchers = {}
        self.call_records = {}
        self.sampling_periods = {}
        self.reviews = {}
        self.score_sheets = {}
        self.rebuttals = {}
        self.high_risk_reviews = {}
        self.coaching_plans = {}
        self.sessions = {}
        self.reports = {}
        self.clock = CLOCK_DEFAULT
        self._counter = itertools.count(1)


db = Store()


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def next_seq():
    """Monotonic insertion sequence, used only as a deterministic tie-break."""
    return next(db._counter)


def clock():
    """Current logical UTC instant."""
    return db.clock


def set_clock(instant):
    db.clock = instant


def base_row(with_version=True):
    """Common fields: id, created_at, updated_at, version (PRD 2.4)."""
    row = {"id": new_id()}
    row["_seq"] = next_seq()
    row["created_at"] = clock()
    if with_version:
        row["updated_at"] = clock()
        row["version"] = 1
    return row


def touch(row):
    """Mark a row mutated: refresh updated_at and increment version.

    A row is written at most once per request, so repeated calls inside one
    cascade are collapsed into a single version increment (PRD 2.8).
    """
    if row is None or "version" not in row:
        return
    try:
        from flask import g
        seen = getattr(g, "_touched_rows", None)
        if seen is None:
            seen = set()
            g._touched_rows = seen
        if row["id"] in seen:
            return
        seen.add(row["id"])
    except RuntimeError:
        pass
    row["updated_at"] = clock()
    row["version"] = row["version"] + 1


def order_rows(rows):
    """PRD 2.3 — list endpoints order by created_at ascending (stable)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
