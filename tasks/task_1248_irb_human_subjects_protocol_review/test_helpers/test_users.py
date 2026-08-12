"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the opaque roles (IrbCoordinator, IrbAdmin,
# ComplianceOfficer): PRD §2.1 says their X-User-ID is not compared against
# any entity id, so a fixed placeholder is canonical.
#
# The entity-backed roles (PrincipalInvestigator -> Investigator,
# Reviewer/IrbChair -> IrbMember) also get shared constants, but those are
# safe ONLY for tests that do not exercise ownership (e.g. 400/404 paths).
# Ownership-gated calls MUST use the per-instance builders below with the
# actual entity id.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "IrbAdmin"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "IrbCoordinator"),
    "officer_headers": build_user_headers("test-officer-1", "ComplianceOfficer"),
    # Fallbacks for non-ownership tests only.
    "pi_headers": build_user_headers("test-pi-1", "PrincipalInvestigator"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "Reviewer"),
    "chair_headers": build_user_headers("test-chair-1", "IrbChair"),
}


def make_pi_headers(investigator_id: str) -> dict:
    """PrincipalInvestigator is entity-backed by Investigator: X-User-ID must
    equal the Investigator.id whenever the call is ownership-gated."""
    return build_user_headers(investigator_id, "PrincipalInvestigator")


def make_reviewer_headers(member_id: str) -> dict:
    """Reviewer is entity-backed by IrbMember: X-User-ID must equal the
    IrbMember.id whenever the call is ownership-gated."""
    return build_user_headers(member_id, "Reviewer")


def make_chair_headers(member_id: str) -> dict:
    """IrbChair is entity-backed by IrbMember and additionally requires the
    member's is_chair flag to be true (PRD §2.1)."""
    return build_user_headers(member_id, "IrbChair")
