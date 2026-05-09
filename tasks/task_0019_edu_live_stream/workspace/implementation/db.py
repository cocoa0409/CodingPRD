"""In-memory data store and helpers for ids, timestamps, system fields."""
import datetime
import threading
import time as time_mod
import uuid


_LOCK = threading.RLock()


def new_id() -> str:
    return str(uuid.uuid4())


def iso_now_ms() -> str:
    """ISO 8601 UTC with three fractional digits, suffix 'Z'.

    Uses the logical Clock entity's `now_ts` (PRD §2.10): "the wall-clock value
    that all time-gated checks ... read." Real wall-clock would diverge from the
    test-driven logical clock and break time-anchored fields like enrolled_at.
    """
    ts = int(store.clock_now_ts)
    now = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"


class _Store:
    def __init__(self):
        self.lock = _LOCK
        self.courses = {}
        self.chapters = {}
        self.syllabus_revisions = {}
        self.instructors = {}
        self.students = {}
        self.enrollments = {}
        self.class_groups = {}
        self.announcements = {}
        self.live_classes = {}
        self.attendances = {}
        self.leave_requests = {}
        self.assignments = {}
        self.submissions = {}
        self.watch_sessions = {}
        self.refund_requests = {}
        self.audit_logs = {}
        # singleton clock
        self.clock_now_ts = int(time_mod.time())

    def reset(self):
        with self.lock:
            self.courses.clear()
            self.chapters.clear()
            self.syllabus_revisions.clear()
            self.instructors.clear()
            self.students.clear()
            self.enrollments.clear()
            self.class_groups.clear()
            self.announcements.clear()
            self.live_classes.clear()
            self.attendances.clear()
            self.leave_requests.clear()
            self.assignments.clear()
            self.submissions.clear()
            self.watch_sessions.clear()
            self.refund_requests.clear()
            self.audit_logs.clear()
            self.clock_now_ts = int(time_mod.time())


store = _Store()


def make_common_fields():
    """Return id, created_at, updated_at, version for a new mutable resource."""
    ts = iso_now_ms()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def make_immutable_fields():
    """Return id, created_at for an immutable/append-only resource."""
    return {
        "id": new_id(),
        "created_at": iso_now_ms(),
    }


def bump(resource):
    """Refresh updated_at and increment version on a mutation."""
    resource["updated_at"] = iso_now_ms()
    resource["version"] = int(resource.get("version", 0)) + 1
