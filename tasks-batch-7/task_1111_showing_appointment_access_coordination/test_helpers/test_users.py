"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Anonymous, PlatformAdmin), and for
# entity-backed roles ONLY in tests whose success does not depend on ownership
# (e.g., 400-on-bad-payload, 404-on-missing-resource calls).
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-caller-1", "Anonymous"),
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    # Entity-backed fallbacks — never use for ownership-gated calls.
    "seller_headers": build_user_headers("test-seller-1", "Seller"),
    "listing_agent_headers": build_user_headers("test-listing-agent-1", "ListingAgent"),
    "buyer_agent_headers": build_user_headers("test-buyer-agent-1", "BuyerAgent"),
}


# Per-instance builders — required for every entity_backed role.
def make_seller_headers(seller_id: str) -> dict:
    """Seller is entity_backed:Seller. Pass the actual Seller.id as user_id
    whenever the call is ownership-gated (approve/decline, blackout management,
    approval-settings update, seller-scoped reads)."""
    return build_user_headers(seller_id, "Seller")


def make_listing_agent_headers(agent_id: str) -> dict:
    """ListingAgent is entity_backed:Agent. Pass the acting Agent.id as user_id
    whenever the call is ownership-gated (listing lifecycle, policy, credential
    issuance/revocation, no-show declaration)."""
    return build_user_headers(agent_id, "ListingAgent")


def make_buyer_agent_headers(agent_id: str) -> dict:
    """BuyerAgent is entity_backed:Agent. Pass the acting Agent.id as user_id
    whenever the call is ownership-gated (request intake, confirm/cancel/
    reschedule, credential redemption, feedback submission)."""
    return build_user_headers(agent_id, "BuyerAgent")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_anonymous_headers(user_id: str = "anon-caller-1") -> dict:
    return build_user_headers(user_id, "Anonymous")
