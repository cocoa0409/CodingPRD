"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "landlord_headers": build_user_headers("test-landlord-1", "Landlord"),
    "renter_headers": build_user_headers("test-renter-1", "Renter"),
    # opaque operator roles: shared constant is the canonical form.
    "underwriting_agent_headers": build_user_headers("uw-agent-1", "UnderwritingAgent"),
    "claims_adjuster_headers": build_user_headers("adjuster-001", "ClaimsAdjuster"),
    "compliance_officer_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
}


def make_landlord_headers(landlord_id: str) -> dict:
    """For Landlord (entity_backed:Landlord). Pass the actual Landlord.id as user_id
    whenever the call is ownership-gated (e.g. creating a Property, filing a Claim)."""
    return build_user_headers(landlord_id, "Landlord")


def make_renter_headers(renter_id: str) -> dict:
    """For Renter (entity_backed:Renter). Pass the actual Renter.id as user_id
    whenever the call is ownership-gated (e.g. creating a RenterEnrollment, paying an invoice)."""
    return build_user_headers(renter_id, "Renter")


def make_underwriting_agent_headers(operator_id: str = "uw-agent-1") -> dict:
    return build_user_headers(operator_id, "UnderwritingAgent")


def make_claims_adjuster_headers(operator_id: str) -> dict:
    """Opaque operator identity — pass a distinct id per adjuster to exercise SoD checks."""
    return build_user_headers(operator_id, "ClaimsAdjuster")


def make_compliance_officer_headers(operator_id: str = "compliance-1") -> dict:
    return build_user_headers(operator_id, "ComplianceOfficer")


def make_platform_admin_headers(operator_id: str = "platform-admin-1") -> dict:
    return build_user_headers(operator_id, "PlatformAdmin")
