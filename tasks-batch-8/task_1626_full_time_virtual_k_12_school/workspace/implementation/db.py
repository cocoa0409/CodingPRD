"""In-memory data store and logical clock.

Storage is process-local only (plain dicts keyed by id). The store starts
empty on every boot; per-test-server isolation wipes state by restarting
the process. No entity is ever seeded at startup.
"""

import uuid
from datetime import datetime, timezone

COLLECTIONS = [
    "districts",
    "students",
    "enrollment_terms",
    "stipends",
    "teachers",
    "teacher_assignments",
    "attendance_records",
    "assessment_windows",
    "test_sites",
    "proctor_assignments",
    "service_deliveries",
]

STORE = {name: {} for name in COLLECTIONS}

_SEQ = {"n": 0}

# Logical clock (PRD section 2.5): startup default is exactly
# 2026-08-01T00:00:00Z; the server never falls back to wall-clock time.
_CLOCK = {"dt": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return _CLOCK["dt"]


def set_clock(dt):
    _CLOCK["dt"] = dt


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def fmt_ts(dt):
    """Render an ISO 8601 UTC timestamp with three fractional digits."""
    d = dt.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def fmt_date(dt):
    """Render the calendar date of `dt` as an ISO 8601 date at midnight UTC."""
    d = dt.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT00:00:00.000Z")


def new_entity(collection, fields):
    """Create and store an entity with common system fields."""
    ts = fmt_ts(now())
    ent = dict(fields)
    ent["id"] = new_id()
    ent["created_at"] = ts
    ent["updated_at"] = ts
    ent["version"] = 1
    ent["_seq"] = next_seq()
    STORE[collection][ent["id"]] = ent
    return ent


def touch(ent):
    """Record a mutation: bump version and updated_at."""
    ent["version"] = ent.get("version", 1) + 1
    ent["updated_at"] = fmt_ts(now())


def get(collection, ent_id):
    if not isinstance(ent_id, str):
        return None
    return STORE[collection].get(ent_id)


def all_of(collection):
    return sorted(STORE[collection].values(), key=lambda e: (e["created_at"], e["_seq"]))


def public(ent):
    """Strip internal keys for serialization."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}
