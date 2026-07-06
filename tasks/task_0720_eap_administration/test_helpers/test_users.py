"""Pre-built role headers for every role in the PRD.

Four roles (ProgramAdmin, CareCoordinator, CrisisCounselor, Employer) carry an
opaque identity — the X-User-ID is never compared to any entity id, so a shared
constant is the canonical form. The Provider role is entity-backed: X-User-ID
must be the acting Provider's id, so ownership-gated calls MUST use
make_provider_headers(provider_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "care_coordinator_headers": build_user_headers("test-coordinator-1", "CareCoordinator"),
    "crisis_counselor_headers": build_user_headers("test-crisis-1", "CrisisCounselor"),
    # Provider shared constant: fallback for non-ownership tests only (e.g. 404,
    # bad-payload, claims where the acting provider need not own the resource).
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
    "employer_headers": build_user_headers("test-employer-1", "Employer"),
}


def make_provider_headers(user_id: str) -> dict:
    """For the entity-backed Provider role. Pass the actual Provider.id as
    user_id whenever the call is ownership-gated (accept/decline/complete a
    referral, or any check comparing X-User-ID to a provider FK)."""
    return build_user_headers(user_id, "Provider")
