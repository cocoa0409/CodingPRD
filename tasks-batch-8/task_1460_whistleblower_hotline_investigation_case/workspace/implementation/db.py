"""In-memory data store and the logical clock.

The store starts empty on every boot; no seeding. All timestamps in the system
are read from the logical clock (PRD section 2.9), which defaults to
2026-08-01T00:00:00Z and is advanced only via POST /_clock/set_current_utc.
"""
import uuid
from datetime import datetime, timezone

DB = {
    "staff_members": {},
    "cases": {},
    "assignments": {},
    "interviews": {},
    "evidence_items": {},
    "determinations": {},
    "remediation_actions": {},
    "retaliation_flags": {},
    "monitoring_plans": {},
    "closure_notices": {},
    "legal_holds": {},
    "reports": {},
    "events": {},
}

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = {"now": DEFAULT_CLOCK}
_SEQ = {"n": 0}


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def next_seq():
    """Monotonic insertion sequence (deterministic tie-break for equal timestamps)."""
    _SEQ["n"] += 1
    return _SEQ["n"]


def now_dt():
    """Current logical-clock instant."""
    return CLOCK["now"]


def set_clock(dt):
    CLOCK["now"] = dt


def fmt_dt(dt):
    """ISO 8601 UTC serialization: seconds precision unless sub-second present."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso():
    return fmt_dt(CLOCK["now"])
