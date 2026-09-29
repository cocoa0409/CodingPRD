"""Pre-built role headers for every role in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator roles: the shared constant is the canonical form because the
# server never compares their X-User-ID to any persisted row.
TEST_USERS = {
    "program_admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    "program_admin_2_headers": build_user_headers("admin-2", "ProgramAdmin"),
    "registrar_headers": build_user_headers("reg-1", "Registrar"),
    # Entity-backed roles: these shared constants are only safe for calls that do
    # not exercise an ownership check (bad payload, missing resource, role denial).
    "learner_headers": build_user_headers("test-learner-1", "Learner"),
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    "corporate_sponsor_headers": build_user_headers("test-sponsor-1", "CorporateSponsor"),
}

# Anonymous is the only role permitted to omit X-User-ID.
ANONYMOUS_HEADERS = {"X-User-Role": "Anonymous", "Content-Type": "application/json"}

PROGRAM_ADMIN_ID = "admin-1"
PROGRAM_ADMIN_2_ID = "admin-2"
REGISTRAR_ID = "reg-1"


def make_learner_headers(learner_id: str) -> dict:
    """Headers for a Learner. Pass the actual Learner.id whenever the call is
    ownership-gated."""
    return build_user_headers(learner_id, "Learner")


def make_instructor_headers(instructor_id: str) -> dict:
    """Headers for an Instructor. Pass the actual Instructor.id whenever the call
    is ownership-gated."""
    return build_user_headers(instructor_id, "Instructor")


def make_sponsor_headers(corporate_account_id: str) -> dict:
    """Headers for a CorporateSponsor. Pass the actual CorporateAccount.id whenever
    the call is ownership-gated."""
    return build_user_headers(corporate_account_id, "CorporateSponsor")


def make_program_admin_headers(user_id: str) -> dict:
    """Headers for a ProgramAdmin acting under a specific opaque operator id.
    Used by the segregation-of-duties scenarios."""
    return build_user_headers(user_id, "ProgramAdmin")


ADMIN = TEST_USERS["program_admin_headers"]
ADMIN2 = TEST_USERS["program_admin_2_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
ANON = ANONYMOUS_HEADERS
