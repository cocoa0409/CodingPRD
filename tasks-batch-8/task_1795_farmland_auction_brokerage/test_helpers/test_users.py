"""Pre-built role headers for every role in the PRD (§2.1).

Seller / BrokerAgent / Buyer are entity-backed roles: for ownership-gated calls
the X-User-ID must be the actual entity id — use the per-instance builders.
PlatformAdmin is opaque: the shared constant is canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Shared constants — safe for opaque PlatformAdmin and for calls whose
    # success does not depend on the caller owning the subject resource.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # Fallbacks for non-ownership contexts only (e.g. 400/404 probes).
    "seller_headers": build_user_headers("test-seller-1", "Seller"),
    "agent_headers": build_user_headers("test-agent-1", "BrokerAgent"),
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
}


def make_seller_headers(user_id: str) -> dict:
    """Seller is entity-backed: pass the actual Seller.id for ownership-gated calls."""
    return build_user_headers(user_id, "Seller")


def make_agent_headers(user_id: str) -> dict:
    """BrokerAgent is entity-backed: pass the actual BrokerAgent.id for
    ownership-gated calls (package/market/auctions/deposits/closings)."""
    return build_user_headers(user_id, "BrokerAgent")


def make_buyer_headers(user_id: str) -> dict:
    """Buyer is entity-backed: pass the actual Buyer.id for bids/acknowledges/reads."""
    return build_user_headers(user_id, "Buyer")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """PlatformAdmin is opaque; the id is never compared to entity ids."""
    return build_user_headers(user_id, "PlatformAdmin")
