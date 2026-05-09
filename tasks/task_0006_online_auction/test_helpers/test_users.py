"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers
from .types import UserRole


# Shared constants — only safe for opaque roles or for tests where the call's success
# does NOT depend on entity ownership. Bidder/Seller calls that touch resources MUST
# use the per-instance builders below with the actual entity id.
TEST_USERS = {
    # opaque roles — shared constant is canonical
    "platform_admin_headers": build_user_headers("platform-admin-1", UserRole.PLATFORM_ADMIN.value),
    "arbitrator_ops_headers": build_user_headers("arbitrator-ops-1", UserRole.ARBITRATOR_OPS.value),
    "anonymous_headers": build_user_headers("anonymous-1", UserRole.ANONYMOUS.value),
    # entity-backed roles — fallback for non-ownership tests only (e.g. malformed bodies, 404)
    "seller_headers": build_user_headers("test-seller-fallback", UserRole.SELLER.value),
    "bidder_headers": build_user_headers("test-bidder-fallback", UserRole.BIDDER.value),
}


def make_seller_headers(seller_id: str) -> dict:
    """For Seller (entity_backed:Seller). Pass the actual Seller.id when the call is ownership-gated."""
    return build_user_headers(seller_id, UserRole.SELLER.value)


def make_bidder_headers(bidder_id: str) -> dict:
    """For Bidder (entity_backed:Bidder). Pass the actual Bidder.id when the call is ownership-gated."""
    return build_user_headers(bidder_id, UserRole.BIDDER.value)


def make_arbitrator_headers(arbitrator_user_id: str = "arbitrator-ops-1") -> dict:
    """ArbitratorOps is opaque; arbitrator_user_id is recorded but not validated against an entity."""
    return build_user_headers(arbitrator_user_id, UserRole.ARBITRATOR_OPS.value)


def make_admin_headers(admin_id: str = "platform-admin-1") -> dict:
    return build_user_headers(admin_id, UserRole.PLATFORM_ADMIN.value)
