"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership. The Grower role is entity-backed (X-User-ID must equal the owning
# GrowerOperation id on ownership-gated calls), so its shared constant is only
# a fallback for tests that never pass an ownership check.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "advisor_headers": build_user_headers("test-advisor-1", "CommodityAdvisor"),
    "compliance_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    # entity_backed role: fallback for non-ownership tests only.
    "grower_headers": build_user_headers("test-grower-1", "Grower"),
}


def make_grower_headers(user_id: str) -> dict:
    """For Grower (entity_backed: GrowerOperation). Pass the actual
    GrowerOperation.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Grower")


def make_advisor_headers(user_id: str) -> dict:
    """For CommodityAdvisor (opaque role) when a specific advisor identity is
    required, e.g. segregation-of-duties scenarios."""
    return build_user_headers(user_id, "CommodityAdvisor")


def make_compliance_headers(user_id: str) -> dict:
    """For ComplianceOfficer (opaque role) when a specific officer identity is
    required, e.g. segregation-of-duties scenarios."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_admin_headers(user_id: str) -> dict:
    """For PlatformAdmin (opaque role) when a specific identity is required."""
    return build_user_headers(user_id, "PlatformAdmin")
