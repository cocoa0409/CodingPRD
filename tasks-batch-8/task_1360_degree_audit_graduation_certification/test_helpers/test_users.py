"""Pre-built role headers for every role in the PRD (§2.1).

Student is entity-backed: for ownership-gated calls, X-User-ID must equal the
owning Student.id — use make_student_headers(student["id"]). Advisor,
RegistrarStaff, and SystemAdmin carry opaque operator identifiers never compared
to an entity id; Advisor decisions do compare X-User-ID against a waiver's
recorded requested_by_user_id for segregation of duties, so distinct advisor
identities matter — use make_advisor_headers("adv-1") etc.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Student calls that are not
# ownership-gated (e.g., 400-on-bad-payload probes or RBAC denials).
TEST_USERS = {
    # Fallback only for non-ownership Student calls; prefer make_student_headers().
    "student_headers": build_user_headers("test-student-1", "Student"),
    "advisor_headers": build_user_headers("adv-1", "Advisor"),
    "registrar_headers": build_user_headers("test-registrar-1", "RegistrarStaff"),
    "sysadmin_headers": build_user_headers("test-sysadmin-1", "SystemAdmin"),
}


def make_student_headers(user_id: str) -> dict:
    """Student role is entity-backed: pass the acting Student.id as user_id
    whenever the call is ownership-gated (own records, own applications)."""
    return build_user_headers(user_id, "Student")


def make_advisor_headers(user_id: str) -> dict:
    """Advisor role with an explicit opaque operator identifier. The identifier
    is compared against a waiver's requested_by_user_id for segregation of
    duties, so pick distinct ids for requester vs decider."""
    return build_user_headers(user_id, "Advisor")


def make_registrar_headers(user_id: str) -> dict:
    """RegistrarStaff role with an explicit opaque operator identifier."""
    return build_user_headers(user_id, "RegistrarStaff")


def make_sysadmin_headers(user_id: str) -> dict:
    """SystemAdmin role (logical clock only)."""
    return build_user_headers(user_id, "SystemAdmin")
