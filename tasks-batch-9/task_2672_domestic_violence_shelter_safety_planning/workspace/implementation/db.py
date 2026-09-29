"""In-memory data store, logical clock and row bookkeeping.

The store is process-local and starts completely empty on every boot: no entity
is ever seeded, preloaded or hardcoded here.  Every row is created by a client
through a declared endpoint.
"""

import itertools
import uuid
from datetime import datetime, timezone

from flask import g

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "staff_members",
    "wellness_checks",
    "clients",
    "hotline_calls",
    "risk_assessments",
    "safety_plans",
    "plan_components",
    "shelters",
    "shelter_units",
    "screening_requests",
    "shelter_admissions",
    "protective_order_cases",
    "landlord_partners",
    "housing_referrals",
    "disclosure_events",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)
        self.clock = CLOCK_EPOCH

    def next_seq(self):
        return next(self._seq)


db = Store()


# ---------------------------------------------------------------------------
# identifiers and timestamps
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def clock_now():
    """The logical UTC clock; the only time source for business decisions."""
    return db.clock


def clock_iso():
    return iso(db.clock)


def clock_date():
    return db.clock.date()


def wall_iso():
    return iso(datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# mutation bookkeeping
# ---------------------------------------------------------------------------

def _touched_set():
    marks = getattr(g, "_touched_rows", None)
    if marks is None:
        marks = set()
        g._touched_rows = marks
    return marks


def mark_fresh(row):
    """Record a just-created row so in-request re-derivation does not bump it past 1."""
    try:
        _touched_set().add(row["id"])
    except RuntimeError:  # pragma: no cover - outside a request context
        pass


def touch(row):
    """Refresh updated_at and increment version, at most once per row per request."""
    if "version" not in row:
        return
    try:
        marks = _touched_set()
    except RuntimeError:  # pragma: no cover
        marks = None
    if marks is not None:
        if row["id"] in marks:
            return
        marks.add(row["id"])
    row["updated_at"] = clock_iso()
    row["version"] = row["version"] + 1


def public(row):
    """Strip internal bookkeeping keys (any key starting with an underscore)."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def public_list(rows):
    return [public(r) for r in rows]


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])
