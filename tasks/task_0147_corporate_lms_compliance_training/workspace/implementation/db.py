"""In-memory data store. Fresh and empty on every process boot.

Per PRD §2.5 the system uses a single deterministic logical clock; it is
initialized at process start to a fixed epoch and only ever advanced via
POST /_clock/set. Timestamps (created_at/updated_at/issued_at/...) are stamped
from this logical clock, NOT the wall clock.
"""

import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


class Store:
    def __init__(self):
        # entity_name -> { id -> record(dict) }
        self.employees = {}
        self.courses = {}
        self.course_prerequisites = {}
        self.learning_paths = {}
        self.path_steps = {}
        self.assignment_rules = {}
        self.enrollments = {}
        self.quiz_attempts = {}
        self.path_enrollments = {}
        self.certificates = {}
        self.tracking_sessions = {}
        self.escalation_events = {}
        # Singleton logical clock state.
        self.clock = {
            "id": new_id(),
            "current_utc": fmt_ts(datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)),
            "created_at": None,
            "updated_at": None,
            "version": 1,
        }
        now = self.clock["current_utc"]
        self.clock["created_at"] = now
        self.clock["updated_at"] = now

    def now(self):
        """Current logical clock as the raw ISO string."""
        return self.clock["current_utc"]


db = Store()
