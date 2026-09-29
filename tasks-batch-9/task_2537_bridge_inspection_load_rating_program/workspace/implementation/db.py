"""In-memory data store, logical clock and common-field helpers.

The store starts completely empty on every boot: nothing is seeded, preloaded or
hardcoded.  Every entity is created by an API call.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: mandatory startup default for the logical clock.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "bridges",
    "personnel",
    "inspections",
    "element_conditions",
    "critical_findings",
    "notification_logs",
    "load_ratings",
    "permit_applications",
    "permit_bridge_analyses",
    "scour_evaluations",
    "plans_of_action",
    "program_cycles",
    "project_candidates",
    "federal_submissions",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """Current logical-clock instant."""
    return db.clock


def set_clock(instant):
    db.clock = instant


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def fmt_date(value):
    """Whole calendar date, UTC (due dates are date-valued quantities)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def new_id():
    return str(uuid.uuid4())


def new_record(fields=None, common=True):
    """Build a record with the system-managed common field set."""
    record = {"id": new_id(), "_seq": db.next_seq()}
    instant = now()
    record["created_at"] = instant
    if common:
        record["updated_at"] = instant
        record["version"] = 1
    if fields:
        record.update(fields)
    return record


def touch(record):
    """PRD 2.5: any state change refreshes updated_at and bumps version."""
    if record is None:
        return None
    record["updated_at"] = now()
    record["version"] = int(record.get("version", 0)) + 1
    return record


def by_creation(records):
    """Default list ordering: creation timestamp ascending (PRD 2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def hours(count):
    return timedelta(hours=count)
