"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlatformAdmin, BillingSpecialist),
# and for tests that do not exercise entity ownership (e.g. 401/403/404 shapes).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "billing_specialist_headers": build_user_headers("test-billing-1", "BillingSpecialist"),
    # Fallbacks for entity_backed roles — use ONLY where ownership is not the
    # subject under test. Ownership-gated calls MUST use the make_* builders.
    "advisor_headers": build_user_headers("test-advisor-1", "Advisor"),
    "benefits_counselor_headers": build_user_headers("test-counselor-1", "BenefitsCounselor"),
    "community_manager_headers": build_user_headers("test-community-1", "CommunityManager"),
    "family_headers": build_user_headers("test-family-1", "Family"),
}


# --- Per-instance builders — required for every entity_backed role ---

def make_platform_admin_headers(user_id="test-admin-1"):
    """PlatformAdmin is opaque; X-User-ID is not compared to any entity id."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_billing_specialist_headers(user_id="test-billing-1"):
    """BillingSpecialist is opaque; X-User-ID is not compared to any entity id."""
    return build_user_headers(user_id, "BillingSpecialist")


def make_advisor_headers(advisor_id):
    """For Advisor (entity_backed:Advisor). Pass the acting Advisor.id so
    inquiry/tour ownership checks (assigned_advisor_id == X-User-ID) pass."""
    return build_user_headers(advisor_id, "Advisor")


def make_counselor_headers(advisor_id):
    """For BenefitsCounselor (entity_backed:Advisor). Pass the VA-certified
    Advisor.id acting as counselor."""
    return build_user_headers(advisor_id, "BenefitsCounselor")


def make_community_manager_headers(community_id):
    """For CommunityManager (entity_backed:Community). Pass the owning
    Community.id so placement/invoice ownership checks pass."""
    return build_user_headers(community_id, "CommunityManager")


def make_family_headers(family_id):
    """For Family (entity_backed:Family). Pass the owning Family.id so
    inquiry/placement ownership checks pass."""
    return build_user_headers(family_id, "Family")
