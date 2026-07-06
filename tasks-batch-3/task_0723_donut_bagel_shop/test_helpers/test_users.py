"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. For the four opaque roles (ShopAdmin, BakeManager, Cashier,
# RouteDriver) X-User-ID is an arbitrary operator id never compared to any entity,
# so the shared constant is the canonical form. For WholesaleClient (entity_backed:
# WholesaleAccount) the shared constant is only a fallback for non-ownership tests;
# ownership-gated calls must use make_wholesale_client_headers(account_id).
TEST_USERS = {
    "shop_admin_headers": build_user_headers("op-shop-admin-1", "ShopAdmin"),
    "bake_manager_headers": build_user_headers("op-bake-manager-1", "BakeManager"),
    "cashier_headers": build_user_headers("op-cashier-1", "Cashier"),
    "route_driver_headers": build_user_headers("op-route-driver-1", "RouteDriver"),
    "wholesale_client_headers": build_user_headers("op-wholesale-client-1", "WholesaleClient"),
}


def make_wholesale_client_headers(account_id: str) -> dict:
    """For WholesaleClient (entity_backed:WholesaleAccount). Pass the acting
    WholesaleAccount.id as X-User-ID whenever the call is ownership-gated."""
    return build_user_headers(account_id, "WholesaleClient")
