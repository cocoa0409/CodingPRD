"""In-memory data store. All state is module-level; reset on fresh boot."""

import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def _now_iso():
    """Logical clock timestamp with 3 fractional digits."""
    now = _logical_clock
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def wall_now_iso():
    """Actual wall-clock timestamp with 3 fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_logical_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _logical_clock


def set_clock(dt):
    global _logical_clock
    _logical_clock = dt


def today():
    """Logical clock's UTC calendar date."""
    return _logical_clock.date()


def now_iso():
    """Logical clock as ISO-8601 with 3 fractional digits."""
    return _now_iso()


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------

schools = {}          # id -> School dict
courses = {}          # id -> Course dict
course_approvals = {} # id -> CourseApproval dict
instructors = {}      # id -> Instructor dict
instructor_approvals = {}  # id -> InstructorApproval dict
offerings = {}        # id -> CourseOffering dict
students = {}         # id -> Student dict
enrollments = {}      # id -> Enrollment dict
attendance_records = {}  # id -> AttendanceRecord dict
exam_attempts = {}    # id -> ExamAttempt dict
certificates = {}     # id -> Certificate dict
refund_requests = {}  # id -> RefundRequest dict
credit_reports = {}   # id -> CreditReport dict
equivalency_grants = {}  # id -> EquivalencyGrant dict
audit_events = []     # list of AuditEvent dicts (append-only)


def touch(entity):
    """Bump updated_at and version on every mutation."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def new_entity(fields=None):
    """Create a new entity with common fields."""
    ent = {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    if fields:
        ent.update(fields)
    return ent


def audit(entity_type, entity_id, event_type, actor_role, actor_id, detail=None):
    """Append an audit event. actor_role/actor_id are 'system' for sweep/cascade."""
    evt = {
        "id": new_id(),
        "created_at": now_iso(),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "event_type": event_type,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "detail": detail or {},
    }
    audit_events.append(evt)
    return evt
