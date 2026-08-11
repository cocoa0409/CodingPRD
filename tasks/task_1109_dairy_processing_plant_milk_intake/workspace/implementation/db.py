"""In-memory data store and logical clock.

Storage is process-local only: plain dicts keyed by id. Nothing is persisted
to disk, and NO entities are seeded at startup — every entity is created via
the declared API surface.
"""
import uuid
from datetime import datetime, timezone

STORE = {
    "producers": {},
    "haulers": {},
    "receipts": {},
    "lab_tests": {},
    "assays": {},
    "settlements": {},
    "runs": {},
    "cip_cycles": {},
    "batches": {},
    "routes": {},
    "permits": {},
    "pools": {},
}

_seq = 0
# Logical clock: starts at 2026-05-01T00:00:00Z and never falls back to
# wall-clock time. Advanced only via POST /dairy/_clock/set_current_utc.
_clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq
    _seq += 1
    return _seq


def base_record():
    """Common fields for every entity: id, created_at, updated_at, version."""
    t = now()
    return {
        "id": new_id(),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    """Refresh updated_at and bump version on every mutation."""
    rec["updated_at"] = now()
    rec["version"] += 1
