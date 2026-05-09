"""Pre-built role headers for every role in the PRD.

Per PRD §2.1:
- Registrar: opaque identity. X-User-ID is an operator id not tied to any persisted entity.
- Finance:   opaque identity. Same — operator id, not compared to any entity id.
- Student:   entity_backed:Student. X-User-ID is the actual Student.id; ownership
             checks compare it to resource.student_id.
- Professor: entity_backed:Professor. X-User-ID is the actual Professor.id; the
             OverLimitApplication endpoints compare it to primary_signer_id /
             secondary_signer_id for the current step.

For Student/Professor any test that exercises ownership / signer identity MUST go
through the per-instance builder make_student_headers(student["id"]) /
make_professor_headers(professor["id"]). The shared TEST_USERS constant is reserved
for Registrar/Finance and for tests that do not exercise ownership (e.g.,
not-found or pure-permission tests).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque-identity roles — the shared constant is canonical.
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "finance_headers": build_user_headers("test-finance-1", "Finance"),

    # Entity-backed roles — these placeholder shared constants exist ONLY for
    # tests that do NOT exercise ownership (e.g., 400-on-bad-payload, 404 on
    # missing resource). For ownership-gated calls, use the per-instance
    # builders below — passing the actual entity's id as X-User-ID.
    "student_headers": build_user_headers("test-student-placeholder", "Student"),
    "professor_headers": build_user_headers("test-professor-placeholder", "Professor"),
}


def make_student_headers(student_id: str) -> dict:
    """For Student (entity_backed:Student). Pass the actual Student.id as
    user_id whenever the call is ownership-gated (any POST under
    /enrollment-requests, /over-limit-applications, or any GET on a
    student-scoped resource)."""
    return build_user_headers(student_id, "Student")


def make_professor_headers(professor_id: str) -> dict:
    """For Professor (entity_backed:Professor). Pass the actual Professor.id
    as user_id whenever the call is signer-gated (sign / reject on an
    OverLimitApplication)."""
    return build_user_headers(professor_id, "Professor")


def make_registrar_headers(label: str = "registrar") -> dict:
    """For Registrar (opaque identity). The user_id is recorded for audit
    but not compared to any entity. Distinct labels are useful when a test
    needs to demonstrate distinct operator principals."""
    return build_user_headers(f"test-{label}", "Registrar")


def make_finance_headers(label: str = "finance") -> dict:
    """For Finance (opaque identity). Same as Registrar — opaque operator id."""
    return build_user_headers(f"test-{label}", "Finance")
