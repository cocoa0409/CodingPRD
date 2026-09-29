"""In-memory data store, logical clock, identifier and timestamp helpers.

Storage is process-local Python dicts only. The store is EMPTY on every boot:
nothing is seeded, preloaded or hardcoded here or anywhere else.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4 -- before any client sets it the logical clock reads exactly this.
LOGICAL_CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# The fourteen collections of PRD 2.4 (ten versioned + four audit rows).
COLLECTIONS = (
    "plan_years",
    "plan_amendments",
    "employees",
    "leave_events",
    "payroll_periods",
    "contribution_records",
    "loan_accounts",
    "loan_certifications",
    "certification_lines",
    "match_allocations",
    "funding_batches",
    "forfeiture_records",
    "correction_adjustments",
    "nondiscrimination_tests",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = LOGICAL_CLOCK_DEFAULT
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


# --------------------------------------------------------------------------
# logical clock / timestamps
# --------------------------------------------------------------------------

def now():
    """The logical clock. Never falls back to wall-clock time."""
    return db.clock


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt_ts(now())


_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


def parse_ts(value):
    """Tolerant ISO 8601 parser. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hour = int(m.group(4) or 0)
    minute = int(m.group(5) or 0)
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro,
                      tzinfo=timezone.utc)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------

def stamp_new(row, versioned=True):
    """Populate id/created_at (+updated_at/version for versioned rows)."""
    ts = now()
    row["id"] = new_id()
    row["_created_dt"] = ts
    row["created_at"] = fmt_ts(ts)
    row["_seq"] = db.next_seq()
    if versioned:
        row["updated_at"] = fmt_ts(ts)
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1."""
    row["updated_at"] = now_iso()
    row["version"] = int(row.get("version", 0)) + 1
    return row


def order_key(row):
    """Default list ordering: creation timestamp ascending (PRD 2.3)."""
    return (row["_created_dt"], row["_seq"])


def rows(collection):
    return sorted(getattr(db, collection).values(), key=order_key)
