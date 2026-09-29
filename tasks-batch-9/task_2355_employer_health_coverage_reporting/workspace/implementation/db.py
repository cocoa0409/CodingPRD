"""In-memory data store, logical clock and common-field helpers.

The store starts EMPTY on every boot.  No entity is ever seeded here: every
record any test needs is built through the declared API surface.
"""

import itertools
import threading
import uuid
from datetime import datetime, timezone

from flask import g

LOCK = threading.RLock()

_seq_counter = itertools.count(1)

# Logical clock startup value pinned by PRD 2.4 / scaffold 1.5.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TABLES = (
    "filing_seasons",
    "controlled_groups",
    "group_members",
    "monthly_headcounts",
    "measurement_cycles",
    "employees",
    "hours_records",
    "employment_events",
    "coverage_offers",
    "furnishing_consents",
    "forms_1095c",
    "monthly_coverage_lines",
    "transmittals",
    "transmittal_errors",
    "penalty_notices",
    "penalty_evidence",
)

# Families that carry created_at / updated_at / version (PRD 2.4).
MUTABLE_TABLES = frozenset(
    [
        "filing_seasons",
        "controlled_groups",
        "group_members",
        "employees",
        "furnishing_consents",
        "forms_1095c",
        "transmittals",
        "transmittal_errors",
        "penalty_notices",
    ]
)


class Store(object):
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        for name in TABLES:
            setattr(self, name, {})

    def table(self, name):
        return getattr(self, name)


db = Store()


# --------------------------------------------------------------------------- #
# time helpers
# --------------------------------------------------------------------------- #
def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def now_iso():
    """Wall-clock instant used for created_at / updated_at / envelope meta."""
    return fmt_dt(datetime.now(timezone.utc))


def clock_now():
    return db.clock


def clock_iso():
    """Logical-clock instant used by every *_at field the spec pins to it."""
    return fmt_dt(db.clock)


def clock_date():
    return db.clock.astimezone(timezone.utc).date()


# --------------------------------------------------------------------------- #
# record helpers
# --------------------------------------------------------------------------- #
def new_id():
    return str(uuid.uuid4())


def _dirty_set():
    s = getattr(g, "_dirty_records", None)
    if s is None:
        s = set()
        g._dirty_records = s
    return s


def insert(table, record):
    """Insert a record, stamping the common fields for its family."""
    record["id"] = record.get("id") or new_id()
    record["_seq"] = next(_seq_counter)
    record["created_at"] = now_iso()
    if table in MUTABLE_TABLES:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
        # A freshly created record must not be version-bumped again in the
        # same request.
        _dirty_set().add(record["id"])
    db.table(table)[record["id"]] = record
    return record


def touch(record):
    """Register a mutation: bump version + updated_at at most once per request."""
    if record is None or "version" not in record:
        return
    seen = _dirty_set()
    if record["id"] in seen:
        return
    seen.add(record["id"])
    record["version"] += 1
    record["updated_at"] = now_iso()


def rows(table):
    """All rows of a table ordered by created_at ascending."""
    return sorted(db.table(table).values(), key=lambda r: r["_seq"])


def serialize(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}
