"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque ProgramAdmin role and for tests that
# do not exercise ownership (400-on-bad-payload, 404-on-missing-resource, ...).
TEST_USERS = {
    # entity_backed role: fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
    # entity_backed role: fallback for non-ownership tests only.
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
    # opaque role: canonical form (PRD §2.1 — never compared to an entity id).
    "admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
}


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id whenever
    the call is ownership-gated (checkout create/return/dispute, intake
    submission, redemption, withdrawal, self reads)."""
    return build_user_headers(user_id, "Member")


def make_volunteer_headers(user_id: str) -> dict:
    """For Volunteer (entity_backed:Volunteer). Pass the actual Volunteer.id
    whenever the call is identity-bound (recording assays, packing, session
    sign-up, assignment cancel)."""
    return build_user_headers(user_id, "Volunteer")


def make_admin_headers() -> dict:
    """ProgramAdmin headers (opaque operator id)."""
    return build_user_headers("test-admin-1", "ProgramAdmin")
