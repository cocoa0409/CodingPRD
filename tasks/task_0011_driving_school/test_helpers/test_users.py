"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes entity-backed roles (Student, Instructor) from opaque
roles (Admin, Examiner, ComplaintHandler).

For entity-backed roles, ownership-gated calls require X-User-ID to equal the
acting entity's id. Tests must call make_student_headers(student["id"]) /
make_instructor_headers(instructor["id"]) — the shared TEST_USERS constants
are only safe for tests whose success does NOT depend on owning the resource.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise
# entity-backed ownership (e.g., 400-on-bad-payload).
TEST_USERS = {
    # Opaque roles: shared constant is canonical
    "admin_headers": build_user_headers("admin-001", "Admin"),
    "examiner_headers": build_user_headers("ex_01", "Examiner"),
    "complaint_handler_headers": build_user_headers("handler_01", "ComplaintHandler"),

    # Entity-backed: shared constants are FALLBACK for non-ownership tests only.
    # For ownership-gated tests, use make_*_headers() builders.
    "student_headers": build_user_headers("test-student-001", "Student"),
    "instructor_headers": build_user_headers("test-instructor-001", "Instructor"),
}


# --- Per-instance builders for entity-backed roles (mandatory for ownership) ---

def make_student_headers(student_id: str) -> dict:
    """For Student (entity_backed:Student). Pass the actual Student.id whenever
    the call is ownership-gated (own profile read, own appointment cancel, etc.)."""
    return build_user_headers(student_id, "Student")


def make_instructor_headers(instructor_id: str) -> dict:
    """For Instructor (entity_backed:Instructor). Pass the actual Instructor.id
    whenever the call is ownership-gated (check-in/check-out)."""
    return build_user_headers(instructor_id, "Instructor")


def make_admin_headers(admin_id: str = "admin-001") -> dict:
    """Admin headers with optional explicit actor id."""
    return build_user_headers(admin_id, "Admin")


def make_examiner_headers(examiner_id: str) -> dict:
    """Examiner headers — examiner_id is opaque but recorded on
    ExamAppointment.examiner_id at booking time. The acting examiner's
    X-User-ID is used for audit purposes."""
    return build_user_headers(examiner_id, "Examiner")


def make_handler_headers(handler_id: str) -> dict:
    """ComplaintHandler headers — must match Complaint.assigned_handler_id at
    escalate/resolve/reject."""
    return build_user_headers(handler_id, "ComplaintHandler")
