"""In-memory data store. Pure Python dicts keyed by id; a fresh process starts
with every store empty (no seeding) and the logical clock at the scaffold-mandated
default instant 2026-08-01T00:00:00Z."""
import uuid
from datetime import datetime, timezone

from timeutil import iso_z

# Entity stores (id -> entity dict)
airports = {}
hangars = {}
rate_schedules = {}
applications = {}
offers = {}
leases = {}
aircraft = {}
certificates = {}
env_records = {}
inspections = {}
findings = {}
eviction_cases = {}
rent_charges = {}

# Logical clock — never falls back to wall time.
_clock = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}

# Monotonic insertion counter used as the created_at tie-break (resources created
# between clock-sets share the same logical created_at).
_seq = {"n": 0}


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_entity(fields):
    """Create a resource dict with the common system-managed field set."""
    now_iso = iso_z(clock_now())
    ent = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    ent.update(fields)
    ent["_seq"] = next_seq()
    return ent


def public(ent):
    """Strip internal bookkeeping keys for serialization."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}
