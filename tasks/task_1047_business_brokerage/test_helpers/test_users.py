"""Pre-built role headers for every role in the PRD (Section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlatformAdmin, Lender, EscrowAgent),
# and for tests that do NOT exercise ownership (e.g. 400/403/404 negative paths).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "lender_headers": build_user_headers("test-lender-1", "Lender"),
    "escrow_agent_headers": build_user_headers("test-escrow-1", "EscrowAgent"),
    # entity_backed fallbacks — only for non-ownership tests.
    "broker_headers": build_user_headers("test-broker-1", "Broker"),
    "seller_headers": build_user_headers("test-seller-1", "Seller"),
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
}


# Per-instance builders — required for every entity_backed role. Pass the real
# entity id so ownership-gated writes see X-User-ID == the resource's owner id.
def make_broker_headers(user_id: str) -> dict:
    """For Broker (entity_backed:Broker). Pass the acting Broker.id."""
    return build_user_headers(user_id, "Broker")


def make_seller_headers(user_id: str) -> dict:
    """For Seller (entity_backed:Seller). Pass the acting Seller.id."""
    return build_user_headers(user_id, "Seller")


def make_buyer_headers(user_id: str) -> dict:
    """For Buyer (entity_backed:Buyer). Pass the acting Buyer.id."""
    return build_user_headers(user_id, "Buyer")


def make_lender_headers(user_id: str = "test-lender-1") -> dict:
    return build_user_headers(user_id, "Lender")


def make_escrow_agent_headers(user_id: str = "test-escrow-1") -> dict:
    return build_user_headers(user_id, "EscrowAgent")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
