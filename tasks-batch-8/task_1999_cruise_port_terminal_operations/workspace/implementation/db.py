"""In-memory data store and logical clock.

Storage is process-local only (plain dicts keyed by id). The store starts
empty on every boot; per-test-server isolation wipes state by restarting
the process. No entity is ever seeded at startup.
"""

import uuid
from datetime import datetime, timezone

COLLECTIONS = [
    "terminals",
    "berths",
    "vessels",
    "port_calls",
    "berth_assignments",
    "manifest_entries",
    "baggage_items",
    "screening_lanes",
    "customs_cases",
    "service_orders",
    "invoices",
    "transport_slots",
    "weather_advisories",
]

STORE = {name: {} for name in COLLECTIONS}

_SEQ = {"n": 0}

# Per-(terminal_id, vehicle_class) monotone queue sequence counters.
_QUEUE_SEQ = {}

# Logical clock: startup default is exactly 2026-08-01T00:00:00Z and never
# falls back to wall-clock time (PRD section 2.4).
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


def next_queue_seq(terminal_id, vehicle_class):
    key = (terminal_id, vehicle_class)
    _QUEUE_SEQ[key] = _QUEUE_SEQ.get(key, 0) + 1
    return _QUEUE_SEQ[key]


def fmt_ts(dt):
    """Render an ISO 8601 UTC timestamp with three fractional digits."""
    d = dt.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


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


def refresh(ent):
    """Derived-value recompute: refresh updated_at WITHOUT a version bump
    (PRD 2.6: recomputed derived values increment version only where the
    owning workflow says so)."""
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
