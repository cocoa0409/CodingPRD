"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
# Adjuster and SIUInvestigator are entity_backed: their shared constants are only used
# for calls that do NOT depend on ownership (e.g., negative RBAC tests).
TEST_USERS = {
    "adjuster_headers": build_user_headers("test-adjuster-1", "Adjuster"),
    "manager_headers": build_user_headers("test-manager-1", "SIUManager"),
    "investigator_headers": build_user_headers("test-investigator-1", "SIUInvestigator"),
    "compliance_headers": build_user_headers("test-compliance-1", "SIUComplianceOfficer"),
}


# Per-instance builders — required for entity_backed roles when the call is ownership-gated.
def make_adjuster_headers(adjuster_id: str) -> dict:
    """For Adjuster (entity_backed:Adjuster). Pass the actual Adjuster.id."""
    return build_user_headers(adjuster_id, "Adjuster")


def make_investigator_headers(investigator_id: str) -> dict:
    """For SIUInvestigator (entity_backed:Investigator). Pass the actual Investigator.id."""
    return build_user_headers(investigator_id, "SIUInvestigator")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    """For SIUManager (opaque). user_id may be any operator identifier."""
    return build_user_headers(user_id, "SIUManager")


def make_compliance_headers(user_id: str = "test-compliance-1") -> dict:
    """For SIUComplianceOfficer (opaque)."""
    return build_user_headers(user_id, "SIUComplianceOfficer")
