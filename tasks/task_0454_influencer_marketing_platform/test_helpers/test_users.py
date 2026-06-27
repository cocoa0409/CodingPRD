"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (ComplianceOfficer, PlatformAdmin),
# and for tests that do not exercise entity ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    # entity_backed roles: shared constants are a fallback for non-ownership tests only
    # (e.g. role-denial / not-found checks). Ownership-gated calls MUST use the builders below.
    "brand_headers": build_user_headers("test-brand-1", "Brand"),
    "creator_headers": build_user_headers("test-creator-1", "Creator"),
}


# Per-instance builders — required for every entity_backed role.
def make_brand_headers(user_id: str) -> dict:
    """For Brand (entity_backed:Brand). Pass the actual Brand.id as user_id
    whenever the call is ownership-gated (campaigns/offers/contracts the brand owns)."""
    return build_user_headers(user_id, "Brand")


def make_creator_headers(user_id: str) -> dict:
    """For Creator (entity_backed:Creator). Pass the actual Creator.id as user_id
    whenever the call is ownership-gated (offers/content the creator owns)."""
    return build_user_headers(user_id, "Creator")


def make_compliance_headers(user_id: str = "test-compliance-1") -> dict:
    """ComplianceOfficer is opaque; X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """PlatformAdmin is opaque; X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "PlatformAdmin")
