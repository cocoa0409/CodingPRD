"""In-memory data store and the server logical clock.

The store is a set of module-level dicts, one per entity collection, keyed by id.
It starts empty on every process boot and is NEVER seeded.
"""
import uuid

from timeutil import parse_dt, iso_format, now_wall

# Startup default for the logical clock (never real wall-clock for domain logic).
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# ---- Collections (all top-level, flat topology) ----
COLLECTIONS = [
    "clients",
    "vaults",
    "artworks",
    "storage_placements",
    "condition_reports",
    "crates",
    "crews",
    "transport_jobs",
    "appraisals",
    "policies",
    "loans",
    "carnets",
    "viewing_rooms",
    "viewing_bookings",
    "invoices",
]

db = {name: {} for name in COLLECTIONS}

_state = {
    "clock": parse_dt(CLOCK_DEFAULT),
    "seq": 0,
}


def reset():
    for name in COLLECTIONS:
        db[name].clear()
    _state["clock"] = parse_dt(CLOCK_DEFAULT)
    _state["seq"] = 0


# ---- Logical clock ----
def get_clock():
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt


# ---- Id / sequence ----
def new_id():
    return str(uuid.uuid4())


def _next_seq():
    _state["seq"] += 1
    return _state["seq"]


# ---- Record lifecycle ----
def new_record(fields, common=True):
    """Create a record dict with system common fields.

    common=True  -> id, created_at, updated_at, version
    common=False -> id, created_at only (immutable records, e.g. ConditionReport)
    """
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = iso_format(now_wall())
    rec["_seq"] = _next_seq()
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Mark a record mutated: bump updated_at and version."""
    rec["updated_at"] = iso_format(now_wall())
    if "version" in rec:
        rec["version"] += 1


def serialize(rec):
    """Public view of a record: drop internal keys (leading underscore)."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
