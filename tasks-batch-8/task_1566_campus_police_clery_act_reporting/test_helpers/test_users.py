"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
# For the entity-backed CampusSecurityAuthority role, use make_csa_headers(csa_id)
# whenever the call is ownership-gated (referral create / forward / own reads).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "SystemAdmin"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "CleryCoordinator"),
    "chief_headers": build_user_headers("test-chief-1", "PoliceChief"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "csa_headers": build_user_headers("test-csa-1", "CampusSecurityAuthority"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "FederalReviewer"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
}


def make_csa_headers(csa_id: str) -> dict:
    """For CampusSecurityAuthority (entity-backed per PRD §2.1). Pass the actual
    CampusSecurityAuthority.id as csa_id whenever the call is ownership-gated
    (referral creation, forward, own-referral reads)."""
    return build_user_headers(csa_id, "CampusSecurityAuthority")
