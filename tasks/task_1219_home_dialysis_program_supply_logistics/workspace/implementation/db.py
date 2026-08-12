"""In-memory data store. Starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone

# Logical clock — startup default per spec; never falls back to wall clock.
_CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}

STORES = {
    "dialysis_programs": {},
    "patients": {},
    "training_attempts": {},
    "home_assessments": {},
    "home_modification_work_orders": {},
    "dialysis_machines": {},
    "maintenance_events": {},
    "emergency_backup_plans": {},
    "supply_orders": {},
    "delivery_appointments": {},
    "treatment_logs": {},
    "clinical_reviews": {},
    "in_center_chairs": {},
    "backup_slot_reservations": {},
    "waste_return_records": {},
    "transition_records": {},
}


def new_id():
    return str(uuid.uuid4())


_SEQ = {"n": 0}


def _next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def now():
    return _CLOCK["now"]


def set_now(dt):
    _CLOCK["now"] = dt


def iso(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    if dt is None:
        return None
    s = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return s


def stamp_new(record):
    t = iso(now())
    record["id"] = new_id()
    record["created_at"] = t
    record["updated_at"] = t
    record["version"] = 1
    record["_seq"] = _next_seq()
    return record


def touch(record):
    record["updated_at"] = iso(now())
    record["version"] = record.get("version", 1) + 1
    return record
