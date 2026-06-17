"""In-memory data store. Starts EMPTY on every boot. No seeding, ever.

Each entity type is a dict keyed by uuid string. Common fields (id, created_at,
updated_at, version) are managed here. created_at/updated_at are ISO 8601 UTC
with three fractional digits; version starts at 1 and increments on mutation
(PRD 2.4).
"""
import itertools
import uuid
from datetime import datetime, timezone

from response import now_iso

# One dict per entity type. Insertion order is preserved (Python 3.7+),
# giving stable created_at-ascending iteration for list endpoints.
customers = {}
vehicles = {}
work_orders = {}
damage_assessments = {}
glass_parts = {}
part_orders = {}
technicians = {}
service_bays = {}
service_appointments = {}
recalibration_jobs = {}
payments = {}
warranties = {}

# Monotonic counter to break created_at ties deterministically (timestamps have
# only millisecond resolution; rapid creates can collide). Sort uses (created_at,
# _seq) so ordering matches creation order exactly.
_seq_counter = itertools.count()

# Test-driving clock (PRD 3.8). None => use real wall clock. When set, it pins
# the instant used for safe_drive_away_at stamping and cure-elapsed checks.
_clock_override = None


def set_clock(dt):
    """Pin the server clock to a timezone-aware UTC datetime."""
    global _clock_override
    _clock_override = dt


def current_utc():
    """The server's current UTC instant (override if set, else wall clock)."""
    if _clock_override is not None:
        return _clock_override
    return datetime.now(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def stamp_new(obj):
    """Attach common fields to a freshly created entity."""
    ts = now_iso()
    obj.setdefault("id", new_id())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = next(_seq_counter)
    return obj


def touch(obj):
    """Mark an entity as mutated: refresh updated_at, bump version by one."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj


def sort_by_created(values):
    return sorted(values, key=lambda o: (o["created_at"], o["_seq"]))


# Fields that are internal-only or not part of the public resource view.
_HIDDEN_PREFIX = "_"


def public(obj):
    """Strip internal-only fields (those prefixed with '_') for the response."""
    return {k: v for k, v in obj.items() if not k.startswith(_HIDDEN_PREFIX)}
