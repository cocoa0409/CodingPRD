"""In-memory data store. Every byte of state lives in module-level dicts that are
empty on import — the store starts empty on every boot. No seeding, no preload."""
import uuid
from datetime import datetime, timezone

# One dict per entity collection, keyed by id.
programs = {}
participants = {}
enrollments = {}
loc_assessments = {}
care_plans = {}
care_plan_goals = {}
attendance_days = {}
transport_legs = {}
medication_orders = {}
medication_administrations = {}
capitation_payments = {}
disenrollment_requests = {}

# Logical clock — settable "current UTC instant" used by time-gated logic
# (PRD §2.9). Defaults to real wall-clock UTC until pinned.
_clock = {"now": None}


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def set_clock(dt):
    _clock["now"] = dt


def clock_now():
    """Return the current logical instant as a timezone-aware datetime."""
    if _clock["now"] is not None:
        return _clock["now"]
    return datetime.now(timezone.utc)
