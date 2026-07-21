"""Pre-built role headers for every role in the PRD (Section 2.1).

Homeowner, Appraiser, and Inspector are entity-backed: their X-User-ID must be
the persisted entity's id whenever an ownership/identity check applies, so use
the per-instance builders below. InvestmentAnalyst, ClosingAgent, and
ComplianceOfficer are opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (e.g. 404-on-missing-resource, bad-payload 400).
TEST_USERS = {
    "homeowner_headers": build_user_headers("test-homeowner-1", "Homeowner"),
    "analyst_headers": build_user_headers("test-analyst-1", "InvestmentAnalyst"),
    "appraiser_headers": build_user_headers("test-appraiser-1", "Appraiser"),
    "closing_agent_headers": build_user_headers("test-closing-1", "ClosingAgent"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "compliance_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
}


# Per-instance builders — required for entity-backed roles; also handy for the
# ComplianceOfficer segregation-of-duties cases that pin specific operator ids.
def make_homeowner_headers(user_id: str) -> dict:
    """For Homeowner (entity_backed:Homeowner). Pass the Homeowner.id."""
    return build_user_headers(user_id, "Homeowner")


def make_appraiser_headers(user_id: str) -> dict:
    """For Appraiser (entity_backed:Appraiser). Pass the Appraiser.id."""
    return build_user_headers(user_id, "Appraiser")


def make_inspector_headers(user_id: str) -> dict:
    """For Inspector (entity_backed:Inspector). Pass the Inspector.id."""
    return build_user_headers(user_id, "Inspector")


def make_analyst_headers(user_id: str = "test-analyst-1") -> dict:
    return build_user_headers(user_id, "InvestmentAnalyst")


def make_closing_agent_headers(user_id: str = "test-closing-1") -> dict:
    return build_user_headers(user_id, "ClosingAgent")


def make_compliance_headers(user_id: str = "test-compliance-1") -> dict:
    """For ComplianceOfficer (opaque). The user_id is recorded as
    proposed_by_user_id / resolved_by_user_id for the SoD barrier."""
    return build_user_headers(user_id, "ComplianceOfficer")
