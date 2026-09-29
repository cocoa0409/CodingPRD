"""In-memory store, logical clock and audit-field helpers.

Storage is purely in-process: plain dicts keyed by id.  Nothing is written to
disk, so re-invoking start.sh always begins with an entirely empty program.
No entity is ever seeded, preloaded or hardcoded here.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "sites",
    "mentors",
    "cohorts",
    "novices",
    "matches",
    "contact_logs",
    "cycles",
    "milestones",
    "attainments",
    "sessions",
    "attendances",
    "disbursements",
    "packets",
)

NOT_FOUND_ERRORS = {
    "sites": "ERR_SITE_NOT_FOUND",
    "mentors": "ERR_MENTOR_NOT_FOUND",
    "cohorts": "ERR_COHORT_NOT_FOUND",
    "novices": "ERR_NOVICE_NOT_FOUND",
    "matches": "ERR_MATCH_NOT_FOUND",
    "contact_logs": "ERR_CONTACT_LOG_NOT_FOUND",
    "cycles": "ERR_OBSERVATION_CYCLE_NOT_FOUND",
    "milestones": "ERR_MILESTONE_NOT_FOUND",
    "attainments": "ERR_ATTAINMENT_NOT_FOUND",
    "sessions": "ERR_SEMINAR_SESSION_NOT_FOUND",
    "attendances": "ERR_SEMINAR_ATTENDANCE_NOT_FOUND",
    "disbursements": "ERR_DISBURSEMENT_NOT_FOUND",
    "packets": "ERR_CERTIFICATION_NOT_FOUND",
}


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = INITIAL_CLOCK
        self._counter = itertools.count(1)

    def seq(self):
        return next(self._counter)


db = Store()


# ---------------------------------------------------------------- time helpers

def now():
    return db.clock


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO-8601 instant.  Returns None when the value is unusable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


# --------------------------------------------------------------- row lifecycle

def new_row(fields, versioned=True):
    stamp = db.clock
    row = {"id": str(uuid.uuid4()), "created_at": iso(stamp)}
    row["_created"] = stamp
    row["_seq"] = db.seq()
    if versioned:
        row["updated_at"] = iso(stamp)
        row["version"] = 1
    row.update(fields)
    return row


def _touched():
    try:
        bag = g.get("_touched_rows", None)
    except RuntimeError:
        return None
    if bag is None:
        bag = set()
        g._touched_rows = bag
    return bag


def touch(row):
    """Bump updated_at/version once per row per request."""
    if row is None or "version" not in row:
        return row
    bag = _touched()
    key = id(row)
    if bag is not None:
        if key in bag:
            return row
        bag.add(key)
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = iso(db.clock)
    return row


def public(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def order_key(row):
    return (row.get("_created") or INITIAL_CLOCK, row.get("_seq") or 0)


def sorted_rows(rows):
    return sorted(rows, key=order_key)


def all_rows(collection):
    return sorted_rows(list(getattr(db, collection).values()))
