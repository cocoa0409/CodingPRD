"""Append-only AuditLogEntry helper."""
from db import make_immutable_fields, store

ROLE_TO_ENUM = {
    "Instructor": "INSTRUCTOR",
    "TeachingAssistant": "TEACHING_ASSISTANT",
    "Student": "STUDENT",
    "AcademicAdmin": "ACADEMIC_ADMIN",
}


def append(actor_role: str, actor_id: str, action: str, subject_type: str, subject_id: str, detail=None):
    row = {
        **make_immutable_fields(),
        "actor_role": ROLE_TO_ENUM.get(actor_role, actor_role),
        "actor_id": actor_id,
        "action": action,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "detail": detail or {},
    }
    store.audit_logs[row["id"]] = row
    return row
