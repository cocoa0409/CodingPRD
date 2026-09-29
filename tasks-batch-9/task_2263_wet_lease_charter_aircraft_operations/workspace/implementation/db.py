"""In-memory data store for the wet-lease / charter aircraft operations API.

The store starts completely empty on every boot.  Nothing is seeded, preloaded
or hardcoded — every entity is created by callers through the declared API.
"""

import uuid
from datetime import datetime, timezone, timedelta

# PRD 2.4: the server-held logical clock starts at exactly this instant on boot.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "lessees",
    "aircraft",
    "crew_members",
    "leases",
    "regulatory_approvals",
    "insurance_certificates",
    "crew_qualifications",
    "flight_legs",
    "substitutions",
    "utilization_periods",
    "settlement_invoices",
    "reliability_reports",
    "return_conditions",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------------------
# timestamps / identifiers
# --------------------------------------------------------------------------

def iso(dt):
    """ISO-8601 UTC with exactly three fractional-second digits and a Z suffix."""
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
    return datetime.now(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def new_row():
    now = iso(wall_now())
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(row):
    """A mutation (including a derived-field recomputation) bumps version."""
    row["updated_at"] = iso(wall_now())
    row["version"] = row["version"] + 1
    return row


def public(row):
    if row is None:
        return None
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))


def clock_now():
    return db.clock


def sort_key(row):
    return (row.get("created_at") or "", row.get("_seq") or 0)


__all__ = [
    "db", "Store", "iso", "wall_now", "new_id", "new_row", "touch", "public",
    "clock_now", "sort_key", "CLOCK_EPOCH", "timedelta",
]
