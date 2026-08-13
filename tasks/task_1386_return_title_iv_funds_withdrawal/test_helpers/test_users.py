"""Pre-built role headers for every role in the PRD.

SystemAdmin, RegistrarClerk, FinancialAidOfficer and BursarClerk are opaque
roles: PRD section 2.1 states their X-User-ID "is an opaque operator
identifier not tied to any persisted entity", so shared constants are the
canonical form. The Student role is entity-backed: for any ownership-gated
call the caller's X-User-ID must equal the owning enrollment's student_id,
so tests must build per-instance headers with make_student_headers(student_id).
Per-instance builders for the opaque roles exist so segregation-of-duties
tests can pin a specific X-User-ID against a case's calculated_by_user_id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "system_admin_headers": build_user_headers("admin-shared-1", "SystemAdmin"),
    "registrar_clerk_headers": build_user_headers("reg-shared-1",
                                                  "RegistrarClerk"),
    "financial_aid_officer_headers": build_user_headers("officer-shared-1",
                                                        "FinancialAidOfficer"),
    "bursar_clerk_headers": build_user_headers("bursar-shared-1",
                                               "BursarClerk"),
    # Fallback only for Student calls that are NOT ownership-gated
    # (e.g., role-rejection tests). Ownership-gated calls must use
    # make_student_headers(<student id>).
    "student_headers": build_user_headers("student-shared-1", "Student"),
}


def make_system_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_registrar_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RegistrarClerk")


def make_financial_aid_officer_headers(user_id: str) -> dict:
    """For FinancialAidOfficer (opaque identity). Pin user_id when a test
    exercises segregation of duties against calculated_by_user_id."""
    return build_user_headers(user_id, "FinancialAidOfficer")


def make_bursar_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BursarClerk")


def make_student_headers(user_id: str) -> dict:
    """For Student (entity-backed identity). Pass the actual Student.id as
    user_id whenever the call is ownership-gated (withdraw, award accept,
    offer respond, payment)."""
    return build_user_headers(user_id, "Student")
