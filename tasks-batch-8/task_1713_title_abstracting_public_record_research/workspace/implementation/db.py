"""In-memory data store and logical clock.

Storage is process-local only (plain dicts keyed by id). The store starts
empty on every boot; per-test-server isolation wipes state by restarting
the process. No entity is ever seeded at startup.
"""

import uuid
from datetime import datetime, timezone

COLLECTIONS = [
    "orders",
    "assignments",
    "documents",
    "checks",
    "reports",
    "curatives",
    "retrievals",
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
    """Render an ISO 8601 UTC timestamp with three fractional digits.

    Used for the audit fields (created_at / updated_at) and the response-meta
    api_request_timestamp, which PRD section 2.2/2.4 pin to millisecond
    precision."""
    d = dt.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def fmt_ts_sec(dt):
    """Render an ISO 8601 UTC timestamp to the second (no fractional digits).

    PRD section 2.5: the logical clock "reads exactly 2026-08-01T00:00:00Z" and
    stamps received_at / delivered_at; "all timestamp comparisons in this
    domain are made to the second." Clock-stamped and clock-derived fields
    (received_at, due_at, delivered_at) therefore render at second precision."""
    d = dt.astimezone(timezone.utc).replace(microsecond=0)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


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
