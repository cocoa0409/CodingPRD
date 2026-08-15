"""Pre-built role headers for every role in the PRD (§2.1, §4).

Shared constants are safe for opaque roles and for tests that do not exercise
ownership. The Student role is entity-backed: when a Student call is
ownership-gated (own account reads, own payments, own enrollment), callers
MUST build headers with the actual Student.id via make_student_headers().
BursarManager/BursarStaff X-User-ID is load-bearing for write-off
segregation of duties, so SoD tests pin it via the make_* builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "student_headers": build_user_headers("test-student-1", "Student"),
    "registrar_headers": build_user_headers("test-registrar-1", "RegistrarStaff"),
    "bursar_staff_headers": build_user_headers("test-bursar-1", "BursarStaff"),
    "bursar_manager_headers": build_user_headers("test-manager-1", "BursarManager"),
}

# Headers carrying no authentication context at all (PRD §2.1 rejection path).
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}


def make_student_headers(user_id: str) -> dict:
    """For the entity-backed Student role: pass the actual Student.id whenever
    the call is ownership-gated (own account/enrollment/payment access)."""
    return build_user_headers(user_id, "Student")


def make_registrar_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RegistrarStaff")


def make_bursar_staff_headers(user_id: str) -> dict:
    """BursarStaff X-User-ID is recorded as writeoff_requester_id on write-off
    requests, so segregation-of-duties tests must pin it explicitly."""
    return build_user_headers(user_id, "BursarStaff")


def make_bursar_manager_headers(user_id: str) -> dict:
    """BursarManager X-User-ID is compared against writeoff_requester_id on
    approval, so segregation-of-duties tests must pin it explicitly."""
    return build_user_headers(user_id, "BursarManager")
