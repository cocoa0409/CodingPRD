"""In-memory data store.

Storage is a set of plain Python dicts keyed by id.  Nothing is persisted and
nothing is ever seeded: every row in here is created by an API caller.
"""

import itertools
import threading
import uuid
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# Collections.  One dict per entity, keyed by id.  ALL START EMPTY.
# --------------------------------------------------------------------------
chassis_models = {}
chassis_units = {}
body_specs = {}
equipment_specs = {}
work_bays = {}
customers = {}
build_configurations = {}
upfit_orders = {}
equipment_installations = {}
electrical_interfaces = {}
build_slots = {}
weight_certifications = {}
compliance_labels = {}
warranty_claims = {}

COLLECTIONS = {
    "chassis_model": chassis_models,
    "chassis": chassis_units,
    "body_spec": body_specs,
    "equipment_spec": equipment_specs,
    "work_bay": work_bays,
    "customer": customers,
    "build_configuration": build_configurations,
    "upfit_order": upfit_orders,
    "equipment_installation": equipment_installations,
    "electrical_interface": electrical_interfaces,
    "build_slot": build_slots,
    "weight_certification": weight_certifications,
    "compliance_label": compliance_labels,
    "warranty_claim": warranty_claims,
}

_lock = threading.RLock()
_seq_counter = itertools.count(1)


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Timestamps.  ISO 8601 UTC with exactly three fractional-second digits and a
# trailing Z, per PRD section 2.4.
# --------------------------------------------------------------------------
def format_ts(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}".format(dt.microsecond // 1000) + "Z"


def wall_now():
    """Real wall-clock instant, used for created_at / updated_at / request meta."""
    return format_ts(datetime.now(timezone.utc))


# --------------------------------------------------------------------------
# Logical clock (PRD section 2.4).  Starts at exactly 2026-08-01T00:00:00Z and
# only ever moves when POST /_clock/set_current_utc says so.  There is no
# fallback to the wall clock.
# --------------------------------------------------------------------------
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_EPOCH}


def clock_now():
    return _clock["now"]


def clock_now_iso():
    return format_ts(_clock["now"])


def clock_today():
    return _clock["now"].date()


def set_clock(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _clock["now"] = dt.astimezone(timezone.utc)


def reset():
    """Only used by tests of this module; never called at import time."""
    for coll in COLLECTIONS.values():
        coll.clear()
    _clock["now"] = CLOCK_EPOCH


# --------------------------------------------------------------------------
# Row helpers
# --------------------------------------------------------------------------
def insert(collection, fields, common_fields=True):
    """Insert a new row.  `id` is a UUID, `created_at` is stamped from the
    logical clock (PRD 2.4: the server does not read the host's wall clock), and
    (unless the entity opts out) `updated_at` mirrors created_at while `version`
    starts at 1.
    """
    now = clock_now_iso()
    row = {"id": new_id(), "created_at": now}
    if common_fields:
        row["updated_at"] = now
        row["version"] = 1
    row.update(fields)
    row["_seq"] = next_seq()
    collection[row["id"]] = row
    return row


def touch(row):
    """Refresh updated_at and bump version once per row per request.

    Every row a cascade touches gets its own version increment and updated_at
    refresh (PRD 2.10); a row visited by several hops of the same request is
    still a single logical mutation, so it is bumped exactly once.
    """
    if row is None:
        return row
    if "version" not in row:
        # Immutable rows (compliance labels) carry no version / updated_at.
        return row
    try:
        from flask import g, has_request_context
        if has_request_context():
            touched = getattr(g, "_touched", None)
            if touched is None:
                touched = set()
                g._touched = touched
            if row["id"] in touched:
                return row
            touched.add(row["id"])
    except Exception:
        pass
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = clock_now_iso()
    return row


def serialize(row):
    """Public JSON projection: everything except internal bookkeeping keys."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sort_key(row):
    """Default list ordering: created_at ascending, insertion order as the
    deterministic tie-break (`id` never participates in any ordering)."""
    return (row.get("created_at") or "", row.get("_seq") or 0)


def all_rows(collection):
    return sorted(collection.values(), key=sort_key)
