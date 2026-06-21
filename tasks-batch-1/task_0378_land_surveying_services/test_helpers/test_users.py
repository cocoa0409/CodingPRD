"""Pre-built role headers for every role in the PRD.

All six roles are entity-backed by the CrewMember aggregate (PRD §2.1): X-User-ID
must be the id of a persisted CrewMember for ownership / authorship / segregation
checks to resolve correctly. The shared TEST_USERS constants are safe ONLY for
tests that do not depend on the caller owning a subject resource (e.g.
403-forbidden-by-role, 401-missing-auth). Any call whose success depends on the
acting CrewMember's id MUST use the per-instance builder with the real id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — for role-denial / auth-missing tests where the X-User-ID
# never needs to match a real owning entity.
TEST_USERS = {
    "coordinator_headers": build_user_headers("test-coordinator-1", "Coordinator"),
    "researcher_headers": build_user_headers("test-researcher-1", "Researcher"),
    "field_tech_headers": build_user_headers("test-fieldtech-1", "FieldTech"),
    "drafter_headers": build_user_headers("test-drafter-1", "Drafter"),
    "surveyor_headers": build_user_headers("test-surveyor-1", "Surveyor"),
    "billing_clerk_headers": build_user_headers("test-billingclerk-1", "BillingClerk"),
}


def make_coordinator_headers(crew_member_id: str) -> dict:
    """Coordinator role backed by the CrewMember with role_type COORDINATOR."""
    return build_user_headers(crew_member_id, "Coordinator")


def make_researcher_headers(crew_member_id: str) -> dict:
    """Researcher role backed by the CrewMember with role_type RESEARCHER."""
    return build_user_headers(crew_member_id, "Researcher")


def make_field_tech_headers(crew_member_id: str) -> dict:
    """FieldTech role backed by the CrewMember with role_type TECH."""
    return build_user_headers(crew_member_id, "FieldTech")


def make_drafter_headers(crew_member_id: str) -> dict:
    """Drafter role backed by the CrewMember with role_type DRAFTER."""
    return build_user_headers(crew_member_id, "Drafter")


def make_surveyor_headers(crew_member_id: str) -> dict:
    """Surveyor role backed by the CrewMember with role_type PLS (the sealer)."""
    return build_user_headers(crew_member_id, "Surveyor")


def make_billing_clerk_headers(crew_member_id: str) -> dict:
    """BillingClerk role backed by the CrewMember with role_type BILLING_CLERK."""
    return build_user_headers(crew_member_id, "BillingClerk")
