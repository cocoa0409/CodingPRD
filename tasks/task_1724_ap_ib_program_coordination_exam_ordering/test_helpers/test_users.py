"""Pre-built role headers for the four roles of PRD §2.1.

`ApCoordinator` and `Registrar` are opaque roles: their X-User-ID is an
operator identifier never compared to any entity id, so the shared constants
are canonical.

`Student` and `Teacher` are entity-backed: ownership checks compare X-User-ID
to a resource's student_id / teacher_id, so any ownership-gated call MUST use
make_student_headers(student["id"]) / make_teacher_headers(teacher["id"]).
The shared student/teacher constants are safe only for tests whose outcome
does not depend on owning a specific row.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "coordinator_headers": build_user_headers(
        "coordinator-1", UserRole.AP_COORDINATOR.value
    ),
    "registrar_headers": build_user_headers(
        "registrar-1", UserRole.REGISTRAR.value
    ),
    # Entity-backed roles — fallback for non-ownership tests only.
    "student_headers": build_user_headers(
        "test-student-1", UserRole.STUDENT.value
    ),
    "teacher_headers": build_user_headers(
        "test-teacher-1", UserRole.TEACHER.value
    ),
}


def make_student_headers(user_id: str) -> dict:
    """Student headers bound to a real Student.id (required for ownership-gated
    calls: registration create/cancel, application create/resubmit, own
    statement, own filtered lists)."""
    return build_user_headers(user_id, UserRole.STUDENT.value)


def make_teacher_headers(user_id: str) -> dict:
    """Teacher headers bound to a real Teacher.id (required for ownership-gated
    calls: complete-training on the record whose teacher_id matches, filing an
    irregularity report on a session the teacher proctors)."""
    return build_user_headers(user_id, UserRole.TEACHER.value)
