"""Pre-built role headers for every role in the PRD.

PlatformAdmin / BookstoreManager / FinanceAdmin carry opaque X-User-ID
values: the server never compares them to an entity id, so shared
constants are canonical.

Faculty and Student are entity-backed: X-User-ID must equal the acting
Faculty / Student record's id on ownership-gated calls, so fixtures and
tests MUST build per-instance headers with make_faculty_headers /
make_student_headers. The shared constants below are only for calls
whose outcome does not depend on owning the target resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: canonical shared form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "manager_headers": build_user_headers("test-manager-1", "BookstoreManager"),
    "finance_headers": build_user_headers("test-finance-1", "FinanceAdmin"),
    # Entity-backed roles: fallback only for non-ownership-gated calls.
    "faculty_headers": build_user_headers("test-faculty-1", "Faculty"),
    "student_headers": build_user_headers("test-student-1", "Student"),
}


def make_faculty_headers(user_id: str) -> dict:
    """Headers for the Faculty role. Pass the real Faculty.id whenever the
    call is ownership-gated (adoption create/patch/submit)."""
    return build_user_headers(user_id, "Faculty")


def make_student_headers(user_id: str) -> dict:
    """Headers for the Student role. Pass the real Student.id whenever the
    call is ownership-gated (orders, returns, IA opt-out, buyback tickets,
    own enrollment drop)."""
    return build_user_headers(user_id, "Student")


def make_manager_headers(user_id: str) -> dict:
    """Headers for a BookstoreManager with a specific operator id (used when
    the scenario pins who committed a buy plan, for segregation-of-duties
    checks at commission issue)."""
    return build_user_headers(user_id, "BookstoreManager")


def make_finance_headers(user_id: str) -> dict:
    """Headers for a FinanceAdmin with a specific operator id (used when the
    scenario pins the issuing operator id)."""
    return build_user_headers(user_id, "FinanceAdmin")
