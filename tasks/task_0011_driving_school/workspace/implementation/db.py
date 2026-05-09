import threading
import uuid

from clock import CLOCK


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.students = {}
        self.instructors = {}
        self.vehicles = {}
        self.course_packages = {}
        self.practice_appointments = {}
        self.exam_appointments = {}
        self.simulator_sessions = {}
        self.training_hour_records = {}
        self.complaints = {}
        self.audit_logs = {}

    def reset(self):
        with self.lock:
            self.students.clear()
            self.instructors.clear()
            self.vehicles.clear()
            self.course_packages.clear()
            self.practice_appointments.clear()
            self.exam_appointments.clear()
            self.simulator_sessions.clear()
            self.training_hour_records.clear()
            self.complaints.clear()
            self.audit_logs.clear()


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:20]


def init_common(record):
    """Set id, created_at, updated_at, version on a new mutable record."""
    record["id"] = new_id()
    record["created_at"] = CLOCK.iso()
    record["updated_at"] = record["created_at"]
    record["version"] = 1
    return record


def init_immutable(record):
    """Set id, created_at on an append-only/immutable record."""
    record["id"] = new_id()
    record["created_at"] = CLOCK.iso()
    return record


def bump(record):
    """Increment version and refresh updated_at on a mutable record."""
    record["version"] = record.get("version", 0) + 1
    record["updated_at"] = CLOCK.iso()


DATA = DB()
