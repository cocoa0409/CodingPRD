"""In-memory data store and logical clock.

Storage is process-local only (plain dicts keyed by id). The store starts
empty on every boot; per-test-server isolation wipes state by restarting
the process. No entity is ever seeded at startup.

Time is governed by a logical clock (PRD section 2.4): the startup value is
exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time.
"""

import uuid
from datetime import datetime, timezone

COLLECTIONS = [
    "cases",
    "participants",
    "search_cases",
    "attempts",
    "notices",
    "blackouts",
    "elections",
    "payouts",
    "transfers",
    "forfeitures",
    "dlrs",
    "logs",
    "expenses",
]

STORE = {name: {} for name in COLLECTIONS}

_SEQ = {"n": 0}

# Logical clock: startup default is exactly 2026-08-01T00:00:00Z.
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
    if dt is None:
        return None
    d = dt.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def new_entity(collection, fields, common=True):
    """Create and store an entity. common=True attaches the common resource
    properties (id, created_at, updated_at, version); append-only logs
    (SearchAttempt, FiduciaryLogEntry) carry only id + created_at."""
    ent = dict(fields)
    ent["id"] = new_id()
    ent["created_at"] = now()
    if common:
        ent["updated_at"] = now()
        ent["version"] = 1
    ent["_seq"] = next_seq()
    STORE[collection][ent["id"]] = ent
    return ent


def touch(ent):
    """Record a mutation of a stored field: bump version, refresh updated_at."""
    ent["version"] = ent.get("version", 1) + 1
    ent["updated_at"] = now()


def get(collection, ent_id):
    if not isinstance(ent_id, str):
        return None
    return STORE[collection].get(ent_id)


def all_of(collection):
    return sorted(
        STORE[collection].values(), key=lambda e: (e["created_at"], e["_seq"])
    )
