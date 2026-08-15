"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# entity-backed identity (votes, ratify) at all.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "analyst_headers": build_user_headers("test-analyst-1", "RealEstateAnalyst"),
    "manager_headers": build_user_headers("test-manager-1", "RealEstateManager"),
    "construction_headers": build_user_headers(
        "test-construction-1", "ConstructionManager"
    ),
    # Entity-backed roles: shared constants are a fallback for non-ownership
    # tests only (e.g., role-denial checks that never reach identity checks).
    "member_headers": build_user_headers("test-member-1", "CommitteeMember"),
    "chair_headers": build_user_headers("test-chair-1", "CommitteeChair"),
}


# Per-instance builders — REQUIRED for entity-backed roles whenever the call is
# identity-gated. CommitteeMember / CommitteeChair compare X-User-ID against a
# CommitteeMember entity's id, so pass the actual member id.
def make_committee_member_headers(member_id: str) -> dict:
    """Headers for a ballot cast by the given CommitteeMember entity id."""
    return build_user_headers(member_id, "CommitteeMember")


def make_committee_chair_headers(member_id: str) -> dict:
    """Headers for a chair acting as the given CommitteeMember entity id."""
    return build_user_headers(member_id, "CommitteeChair")
