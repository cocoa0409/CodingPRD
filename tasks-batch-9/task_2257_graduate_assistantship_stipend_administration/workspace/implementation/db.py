"""In-memory data store and logical clock.

The store starts EMPTY on every boot.  Nothing is ever seeded, preloaded or
hardcoded here: every row is created through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.10: the logical clock's value at startup is exactly 2026-08-01T00:00:00Z
# and it never falls back to real wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.academic_terms = {}
        self.departments = {}
        self.stipend_policies = {}
        self.pay_periods = {}
        self.students = {}
        self.funding_sources = {}
        self.appointments = {}
        self.funding_allocations = {}
        self.stipend_disbursements = {}
        self.renewal_decisions = {}
        self.tax_assessments = {}
        self._seq = itertools.count(1)
        self._mut = itertools.count(1)
        self.clock = CLOCK_DEFAULT


db = Store()


# --------------------------------------------------------------------------
# logical clock helpers
# --------------------------------------------------------------------------
def now_dt():
    return db.clock


def iso(dt):
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def now_iso():
    return iso(db.clock)


def today():
    return db.clock.date()


def set_clock(dt):
    db.clock = dt.astimezone(timezone.utc)


def next_seq():
    return next(db._seq)


def next_mut():
    return next(db._mut)


# --------------------------------------------------------------------------
# row helpers -- common system fields: id / created_at / updated_at / version
# --------------------------------------------------------------------------
def insert(collection, data):
    row = dict(data)
    ts = now_iso()
    row["id"] = str(uuid.uuid4())
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    row["_seq"] = next_seq()
    row["_mut"] = next_mut()
    collection[row["id"]] = row
    return row


def touch(row):
    """Record a mutation: refresh updated_at and increment version by one."""
    row["updated_at"] = now_iso()
    row["version"] = row["version"] + 1
    row["_mut"] = next_mut()
    return row


def update(row, **fields):
    """Apply field changes.  Bumps updated_at/version once when something changed."""
    changed = False
    for key, value in fields.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def force_update(row, **fields):
    """Apply field changes and always bump updated_at/version exactly once."""
    for key, value in fields.items():
        row[key] = value
    touch(row)
    return True
