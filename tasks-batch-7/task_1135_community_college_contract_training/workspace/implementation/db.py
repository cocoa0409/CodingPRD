"""In-memory data store and the logical clock.

The store starts completely empty on every boot. No seeding of any kind.
The logical clock reads exactly 2026-05-01T00:00:00Z before any clock call
and never falls back to wall-clock time (PRD section 2.5).
"""

import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

COLLECTIONS = [
    "employers",
    "assessments",
    "agreements",
    "programs",
    "applications",
    "instructors",
    "venues",
    "cohorts",
    "sessions",
    "assignments",
    "participants",
    "invoices",
    "reports",
]

store = {name: {} for name in COLLECTIONS}

_clock = {"now": datetime(2026, 5, 1, tzinfo=timezone.utc)}


def now():
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt


def new_id():
    return str(uuid.uuid4())


def touch(rec):
    """Refresh updated_at and bump version (PRD 2.4: every mutation, direct or cascade)."""
    from util import fmt_dt

    rec["updated_at"] = fmt_dt(now())
    rec["version"] = int(rec.get("version", 1)) + 1


def stamp_new(rec):
    from util import fmt_dt

    ts = fmt_dt(now())
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    return rec
