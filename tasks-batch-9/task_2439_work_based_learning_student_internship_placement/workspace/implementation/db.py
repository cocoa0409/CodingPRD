"""In-memory data store and the logical clock (PRD 2.4, 2.5).

The store is empty on every boot - nothing is seeded, preloaded or hardcoded.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: fixed startup default; the server never reads the host wall clock.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "employer_partners",
    "worksites",
    "safety_reviews",
    "supervisors",
    "agreements",
    "students",
    "work_permits",
    "placements",
    "training_plans",
    "learning_objectives",
    "timesheet_entries",
    "evaluation_cycles",
    "incident_reports",
    "placement_outcomes",
)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------------------
# clock helpers
# --------------------------------------------------------------------------

def now_dt():
    return db.clock


def now_ts():
    """ISO 8601 UTC with exactly three fractional digits."""
    return fmt_ts(db.clock)


def fmt_ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def today():
    """Logical clock date as a date object."""
    return db.clock.date()


def today_str():
    return db.clock.date().isoformat()


def add_days(date_str, days):
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    return (d + timedelta(days=days)).isoformat()


def to_date(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def days_between(from_date_str, to_date_str):
    return (to_date(to_date_str) - to_date(from_date_str)).days


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def new_record(with_common=True):
    rec = {"id": new_id(), "created_at": now_ts()}
    if with_common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Every mutation - direct or cascaded - refreshes updated_at and bumps version."""
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 0) + 1
    return rec


def apply_changes(rec, **fields):
    """Set fields, returning True when at least one value actually changed."""
    changed = False
    for key, value in fields.items():
        if rec.get(key) != value:
            rec[key] = value
            changed = True
    return changed


def set_and_touch(rec, **fields):
    if apply_changes(rec, **fields):
        touch(rec)
        return True
    return False


def by_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def by_created_desc(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
