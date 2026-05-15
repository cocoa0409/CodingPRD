"""In-memory data store. Each entity has its own dict keyed by id."""
from __future__ import annotations

import threading
import uuid
from typing import Any

from .clock import CLOCK, format_iso


# Single lock — request handlers run under this for atomic cascades.
LOCK = threading.RLock()


class Store:
    def __init__(self) -> None:
        # entity_name -> { id -> dict }
        self.course_categories: dict[str, dict[str, Any]] = {}
        self.courses: dict[str, dict[str, Any]] = {}
        self.course_versions: dict[str, dict[str, Any]] = {}
        self.instructors: dict[str, dict[str, Any]] = {}
        self.instructor_availabilities: dict[str, dict[str, Any]] = {}
        self.classrooms: dict[str, dict[str, Any]] = {}
        self.online_rooms: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.enrollments: dict[str, dict[str, Any]] = {}
        self.trainees: dict[str, dict[str, Any]] = {}
        self.check_ins: dict[str, dict[str, Any]] = {}
        self.exam_attempts: dict[str, dict[str, Any]] = {}
        self.evaluations: dict[str, dict[str, Any]] = {}
        self.credit_pools: dict[str, dict[str, Any]] = {}
        self.credit_adjustments: dict[str, dict[str, Any]] = {}
        self.certificate_templates: dict[str, dict[str, Any]] = {}
        self.certificates: dict[str, dict[str, Any]] = {}
        self.sync_events: dict[str, dict[str, Any]] = {}
        self.audit_logs: dict[str, dict[str, Any]] = {}

        # uniqueness indexes
        self.course_code_uniq: dict[str, str] = {}  # code -> course_id
        self.trainee_employee_no_uniq: dict[str, str] = {}  # employee_no -> trainee_id
        self.classroom_name_uniq: dict[str, str] = {}  # name -> classroom_id
        self.cert_template_by_course: dict[str, str] = {}  # course_id -> template_id
        self.verification_code_uniq: dict[str, str] = {}  # verification_code -> cert_id


_STORE = Store()


def get_store() -> Store:
    return _STORE


def reset_store() -> None:
    global _STORE
    _STORE = Store()


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return format_iso(CLOCK.now)  # type: ignore[return-value]


def common_fields_create() -> dict[str, Any]:
    """Returns id + created_at + updated_at + version=0 fields."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 0,
    }


def common_fields_append_only() -> dict[str, Any]:
    """Returns id + created_at only (for immutable rows)."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
    }


def bump_version(entity: dict[str, Any]) -> None:
    if "version" in entity:
        entity["version"] = int(entity.get("version", 0)) + 1
    entity["updated_at"] = now_iso()
