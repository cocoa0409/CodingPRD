"""In-memory data store, logical clock and row bookkeeping.

Storage is Python dicts keyed by id.  Nothing is seeded at import time or at
boot: every row in this store is created by an API caller.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

LOGICAL_CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
# PRD 2.4: "Before any client sets it, the logical clock reads exactly
# 2026-08-01T00:00:00Z".  Every server-written domain instant *is* the logical
# clock instant, so it is written with the clock's own reading rather than
# re-serialised into the created_at/updated_at three-fraction-digit form.
LOGICAL_CLOCK_EPOCH_TEXT = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------- collections
COLLECTIONS = (
    "policies",
    "skill_categories",
    "search_firms",
    "external_companies",
    "directors",
    "skill_ratings",
    "candidates",
    "directorships",
    "screens",
    "interviews",
    "committees",
    "assignments",
    "slates",
    "nominees",
    "votes",
    "onboarding_items",
    "comp_awards",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = LOGICAL_CLOCK_EPOCH
        self.clock_text = LOGICAL_CLOCK_EPOCH_TEXT
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


# ------------------------------------------------------------------ timestamps
def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now():
    return iso_ms(datetime.now(timezone.utc))


def clock_instant():
    """The logical clock instant, exactly as the clock reads it."""
    return db.clock_text


def clock_date():
    return db.clock.date()


def new_id():
    return str(uuid.uuid4())


# ------------------------------------------------------------------ mutations
def _touched_set():
    try:
        return g._touched_rows
    except (AttributeError, RuntimeError):
        try:
            g._touched_rows = set()
            return g._touched_rows
        except RuntimeError:
            return None


def touch(row):
    """Refresh updated_at and increment version once per request per row."""
    if row is None or "version" not in row:
        return row
    row["updated_at"] = wall_now()
    marks = _touched_set()
    if marks is None:
        row["version"] = row["version"] + 1
        return row
    if row["id"] not in marks:
        marks.add(row["id"])
        row["version"] = row["version"] + 1
    return row


def new_row(fields, common=True):
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = wall_now()
    if common:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def seq_of(row):
    return row.get("_seq", 0)


def add_days(d, days):
    return d + timedelta(days=days)


def public(row):
    """Row representation for the wire: private bookkeeping keys removed."""
    if row is None:
        return None
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))


def public_list(rows):
    return [public(r) for r in rows]
