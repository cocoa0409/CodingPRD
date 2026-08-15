"""Pre-built role headers for every role in the PRD (section 2.1).

PlatformAdmin, ClosingOfficer, and EscrowOfficer carry opaque user ids (never
compared to an entity id), so shared constants are canonical for them.

ListingAgent and SellingAgent carry the acting BrokerAgent's id in X-User-ID;
ownership checks compare resource foreign keys against it. For those roles the
per-instance builders below are mandatory whenever a call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "closing_officer_headers": build_user_headers("test-closing-1", "ClosingOfficer"),
    "escrow_officer_headers": build_user_headers("test-escrow-1", "EscrowOfficer"),
    # Entity-backed roles — fallback for probes that do NOT exercise ownership
    # (e.g. RBAC denials, bad-payload 400s). Never use these for listing-side
    # or buyer-side ownership-gated calls.
    "listing_agent_headers": build_user_headers("test-listing-agent-1", "ListingAgent"),
    "selling_agent_headers": build_user_headers("test-selling-agent-1", "SellingAgent"),
}


def make_listing_agent_headers(agent_id: str) -> dict:
    """ListingAgent headers whose X-User-ID is the acting BrokerAgent's id.
    Required for listing lifecycle actions and offer accept/reject/counter,
    where the server compares the listing's foreign keys to X-User-ID."""
    return build_user_headers(agent_id, "ListingAgent")


def make_selling_agent_headers(agent_id: str) -> dict:
    """SellingAgent headers whose X-User-ID is the acting BrokerAgent's id.
    Required for offer submission/withdraw/fail and contingency outcomes,
    where the server compares the offer's selling_agent_id to X-User-ID."""
    return build_user_headers(agent_id, "SellingAgent")
