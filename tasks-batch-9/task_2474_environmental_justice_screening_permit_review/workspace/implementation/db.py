"""In-memory data store, logical clock, id / timestamp / version helpers.

Storage is process-local dictionaries keyed by id.  The store is EMPTY on every
boot: no entity is seeded, preloaded or hardcoded anywhere.  Tests build every
precondition through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# The logical clock reads exactly this instant before any client moves it and
# never falls back to the host wall clock (PRD 2.5).
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "screening_areas",
    "burden_indicators",
    "facilities",
    "permit_applications",
    "applicability_determinations",
    "assessments",
    "participation_plans",
    "venues",
    "public_meetings",
    "public_comments",
    "permit_conditions",
    "permit_decisions",
    "community_complaints",
    "inspections",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)
        self.clock = INITIAL_CLOCK

    def next_seq(self):
        return next(self._seq)


db = Store()


# ------------------------------------------------------------------ clock
def clock_now():
    return db.clock


def clock_date():
    return db.clock.date()


def clock_year():
    return db.clock.year


def set_clock(instant):
    db.clock = instant


def iso_ts(moment):
    """ISO 8601 UTC with exactly three fractional digits."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def logical_now_iso():
    return iso_ts(db.clock)


def real_now_iso():
    return iso_ts(datetime.now(timezone.utc))


def iso_date(value):
    return value.isoformat() if value is not None else None


# ------------------------------------------------------------------ rows
def new_id():
    return str(uuid.uuid4())


def _fresh_marker(row_id):
    marked = getattr(g, "_ej_touched", None)
    if marked is None:
        marked = set()
        g._ej_touched = marked
    marked.add(row_id)


def new_row(full_audit=True):
    """Create the common-field skeleton for a new row."""
    stamp = logical_now_iso()
    row = {"id": new_id(), "created_at": stamp}
    if full_audit:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = db.next_seq()
    try:
        _fresh_marker(row["id"])
    except RuntimeError:  # outside a request context
        pass
    return row


def touch(row):
    """Mark a row as mutated: refresh updated_at and bump version by exactly 1.

    A row is bumped at most once per request (PRD 2.4 / 2.8: each row the server
    touches in a request is one real mutation of that row).
    """
    if row is None:
        return
    try:
        marked = getattr(g, "_ej_touched", None)
        if marked is None:
            marked = set()
            g._ej_touched = marked
    except RuntimeError:
        marked = set()
    row["updated_at"] = logical_now_iso()
    if row["id"] in marked:
        return
    marked.add(row["id"])
    if "version" in row:
        row["version"] = row["version"] + 1


# ------------------------------------------------------------------ queries
def ordered(rows):
    """Default list ordering: created_at ascending (insertion order on ties)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def clock_minus_days(days):
    return db.clock - timedelta(days=days)
