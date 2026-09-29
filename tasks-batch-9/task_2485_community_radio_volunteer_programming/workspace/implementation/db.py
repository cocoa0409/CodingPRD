"""In-memory data store, server-held logical clock, and row bookkeeping.

The store is EMPTY on every boot.  Nothing is seeded, preloaded, or hardcoded;
every record a caller sees was created through the declared API surface.
"""

import calendar
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# --------------------------------------------------------------------------
# Logical clock (PRD 2.4).  Nothing in this system reads the host wall clock.
# Station-local time is identical to UTC.
# --------------------------------------------------------------------------

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.current = CLOCK_DEFAULT

    def set(self, moment):
        self.current = moment

    @property
    def now(self):
        return self.current


clock = Clock()


# --------------------------------------------------------------------------
# Stores
# --------------------------------------------------------------------------

class DB:
    def __init__(self):
        self.volunteers = {}
        self.certifications = {}
        self.proposals = {}
        self.votes = {}
        self.programs = {}
        self.grids = {}
        self.slots = {}
        self.episodes = {}
        self.entries = {}
        self.spots = {}
        self.incidents = {}
        self.drives = {}
        self.shifts = {}
        self.premiums = {}
        self.pledges = {}
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


db = DB()


# --------------------------------------------------------------------------
# Row helpers
# --------------------------------------------------------------------------

def begin_request():
    g.dirty = {}
    g.created = set()


def new_row(store, fields, versioned=True):
    row = dict(fields)
    row["id"] = str(uuid.uuid4())
    row["_seq"] = db.next_seq()
    row["created_at"] = clock.now
    if versioned:
        row["updated_at"] = clock.now
        row["version"] = 1
    store[row["id"]] = row
    try:
        g.created.add(row["id"])
    except (RuntimeError, AttributeError):  # pragma: no cover
        pass
    return row


def touch(row):
    """Mark a versioned row as mutated during this request.

    Each mutated record independently refreshes its own updated_at and advances
    its own version by exactly one for the request (PRD 2.5 / 2.9).
    """
    if row is None or "version" not in row:
        return
    try:
        g.dirty[row["id"]] = row
    except (RuntimeError, AttributeError):  # pragma: no cover
        pass


def commit():
    dirty = getattr(g, "dirty", None)
    if not dirty:
        return
    created = getattr(g, "created", set())
    for row_id, row in list(dirty.items()):
        if row_id in created:
            continue
        row["updated_at"] = clock.now
        row["version"] = row.get("version", 0) + 1
    g.dirty = {}


def ordered(store, predicate=None):
    rows = [r for r in store.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


# --------------------------------------------------------------------------
# Date / time helpers
# --------------------------------------------------------------------------

def add_months(moment, months):
    year = moment.year + (moment.month - 1 + months) // 12
    month = (moment.month - 1 + months) % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def whole_months_between(start_date, moment):
    """Whole calendar months elapsed, floored (PRD 3.1)."""
    base = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
    if moment <= base:
        return 0
    months = (moment.year - base.year) * 12 + (moment.month - base.month)
    while months > 0 and add_months(base, months) > moment:
        months -= 1
    while add_months(base, months + 1) <= moment:
        months += 1
    return max(0, months)


def quarter_start(moment):
    first_month = ((moment.month - 1) // 3) * 3 + 1
    return datetime(moment.year, first_month, 1, tzinfo=timezone.utc)


def plus_hours(moment, hours):
    return moment + timedelta(hours=hours)


def plus_days(moment, days):
    return moment + timedelta(days=days)
