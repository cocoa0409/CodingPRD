"""In-memory data store. Starts completely empty on every boot — no seeding."""

import random
import string
import threading
import uuid
from datetime import datetime, timezone

LOCK = threading.RLock()

# Logical clock (PRD §2.8): startup value is exactly 2026-08-01T00:00:00Z.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "standard_domains",
    "providers",
    "rating_cycles",
    "self_assessments",
    "staff_credentials",
    "observers",
    "observation_visits",
    "observation_scores",
    "appeals",
    "data_disputes",
    "improvement_grants",
    "grant_expenditures",
    "coaching_allocations",
    "coaching_sessions",
    "subsidy_claims",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.logical_clock = CLOCK_START
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()


def now():
    """Current logical-clock instant."""
    return DB.logical_clock


def today():
    """Current logical-clock calendar date."""
    return DB.logical_clock.date()


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def wall_now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def base_record(**fields):
    """Create a record with the full common-field set (id/created_at/updated_at/version)."""
    rec = {
        "id": new_id(),
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
    }
    rec["_seq"] = DB.next_seq()
    rec.update(fields)
    return rec


def touch(rec):
    """Refresh updated_at and bump version by exactly 1 (PRD §2.4)."""
    if rec is None:
        return rec
    rec["updated_at"] = now()
    rec["version"] = int(rec.get("version", 0)) + 1
    return rec


def sort_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
