"""In-memory data store. Fresh, empty state on every process boot.

No entity is ever seeded here -- the store starts empty and every entity is
constructed through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

# --- entity tables (dicts keyed by id) -------------------------------------
policies = {}
auditors = {}
class_codes = {}
selection_runs = {}
work_orders = {}
records_requests = {}
appointments = {}
allocations = {}
exposures = {}
certificates = {}
results = {}
disputes = {}
billings = {}
mod_revisions = {}

# --- logical clock ----------------------------------------------------------
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
_clock = {"now": datetime(2026, 8, 1, tzinfo=timezone.utc)}

# --- insertion-order counter for stable sorting -----------------------------
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def parse_dt(value):
    """Parse an ISO 8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with 'Z'.

    Fractional seconds are omitted when exactly zero, rendered with three
    digits when millisecond-aligned, otherwise six digits. This keeps
    whole-second values (the common case) byte-identical to client input.
    """
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    us = dt.microsecond
    if us == 0:
        return base + "Z"
    if us % 1000 == 0:
        return base + ".{:03d}Z".format(us // 1000)
    return base + ".{:06d}Z".format(us)


def now_iso():
    return fmt_dt(clock_now())


def new_entity(fields):
    """Create a bare entity dict with the standard system-managed fields."""
    ent = {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": next_seq(),
    }
    ent.update(fields)
    return ent


def touch(entity):
    """Refresh updated_at and bump version (a full mutation)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def touch_no_version(entity):
    """Refresh updated_at only (derived-field recomputation)."""
    entity["updated_at"] = now_iso()


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def by_created(entities):
    return sorted(entities, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))
