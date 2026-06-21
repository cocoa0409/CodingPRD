"""Pre-built role headers for every role in the PRD.

ListingAgent and BuyerAgent are entity_backed by the Agent record: X-User-ID
must be the acting Agent's id. Anonymous is an opaque operator identifier not
tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the opaque Anonymous role, and for tests that do
# not exercise ownership (e.g. 403-forbidden-role, 404-not-found).
TEST_USERS = {
    "anonymous_headers": build_user_headers("operator-1", "Anonymous"),
    # Entity-backed fallbacks for non-ownership tests only (e.g. forbidden-role).
    "listing_agent_headers": build_user_headers("test-listing-agent-1", "ListingAgent"),
    "buyer_agent_headers": build_user_headers("test-buyer-agent-1", "BuyerAgent"),
}


def make_listing_agent_headers(agent_id: str) -> dict:
    """For the sell side (entity_backed:Agent). Pass the acting Agent's id as
    X-User-ID whenever the call is ownership-gated against listing_agent_id."""
    return build_user_headers(agent_id, "ListingAgent")


def make_buyer_agent_headers(agent_id: str) -> dict:
    """For the buy side (entity_backed:Agent). Pass the acting Agent's id as
    X-User-ID whenever the call is ownership-gated against buyer_agent_id."""
    return build_user_headers(agent_id, "BuyerAgent")


def anon_headers() -> dict:
    """Anonymous operator surface headers."""
    return build_user_headers("operator-1", "Anonymous")
