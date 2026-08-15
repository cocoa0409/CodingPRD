"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles, and for ListingAgent tests that do
# not exercise ownership (e.g., 400-on-bad-payload or calls on missing resources).
TEST_USERS = {
    # entity_backed role (ListingAgent X-User-ID is the Agent id, PRD §2.1):
    # shared constant is a fallback for non-ownership tests only.
    "listing_agent_headers": build_user_headers("test-listing-agent-1", "ListingAgent"),
    # opaque roles: shared constant is the canonical form.
    "marketing_coordinator_headers": build_user_headers("test-coordinator-1", "MarketingCoordinator"),
    "compliance_officer_headers": build_user_headers("test-officer-1", "ComplianceOfficer"),
    "marketing_director_headers": build_user_headers("test-director-1", "MarketingDirector"),
    "portal_webhook_headers": build_user_headers("test-webhook-1", "PortalWebhook"),
}


def make_listing_agent_headers(user_id: str) -> dict:
    """For ListingAgent (entity-backed by Agent). Pass the actual Agent.id as
    user_id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "ListingAgent")
