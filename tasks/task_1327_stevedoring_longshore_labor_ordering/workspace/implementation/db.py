"""In-memory data store. Starts completely empty on every boot — no seeding."""
import itertools
import uuid
from datetime import datetime, timezone

STORE = {
    "vessel_calls": {},
    "shift_windows": {},
    "gang_orders": {},
    "workers": {},
    "dispatch_assignments": {},
    "equipment_units": {},
    "equipment_assignments": {},
    "move_records": {},
    "damage_claims": {},
    "safety_incidents": {},
    "timesheet_entries": {},
    "invoices": {},
}

_seq = itertools.count(1)


def next_seq():
    """Monotonic creation sequence — secondary ordering key when created_at ties."""
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def new_resource(kind):
    """Create the base record with the common system-managed fields."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "_kind": kind,
    }


def save(kind, rec):
    STORE[kind][rec["id"]] = rec
    return rec


def get(kind, rid):
    return STORE[kind].get(rid)


def all_of(kind):
    return STORE[kind].values()


def touch(rec):
    """Every modification refreshes updated_at and increments version."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def pub(rec):
    """Public serialization — internal bookkeeping keys are hidden."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
