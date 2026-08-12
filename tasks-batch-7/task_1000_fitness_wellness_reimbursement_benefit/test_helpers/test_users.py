"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for opaque roles (X-User-ID is never compared to an entity id).
TEST_USERS = {
    "benefits_admin_headers": build_user_headers("test-admin-1", "BenefitsAdmin"),
    "claims_reviewer_headers": build_user_headers("test-reviewer-1", "ClaimsReviewer"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    "platform_admin_headers": build_user_headers("test-platform-1", "PlatformAdmin"),
    # Fallbacks for entity-backed roles — only for tests that do NOT exercise ownership.
    "member_headers": build_user_headers("test-member-1", "Member"),
    "provider_operator_headers": build_user_headers("test-provider-1", "ProviderOperator"),
}


def make_member_headers(user_id: str) -> dict:
    """For Member (entity-backed by Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Member")


def make_provider_operator_headers(user_id: str) -> dict:
    """For ProviderOperator (entity-backed by Provider). Pass the actual Provider.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "ProviderOperator")
