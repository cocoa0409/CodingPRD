"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (WholesaleAdmin, SalesRep, RouteDriver,
# CreditManager) and for tests that do not exercise ownership (400 / 404 / role-only).
# StoreManager is entity_backed:Retailer — see make_store_manager_headers below.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "WholesaleAdmin"),
    "sales_rep_headers": build_user_headers("test-salesrep-1", "SalesRep"),
    "route_driver_headers": build_user_headers("test-driver-1", "RouteDriver"),
    "credit_manager_headers": build_user_headers("test-credit-1", "CreditManager"),
    # Fallback for non-ownership StoreManager tests only.
    "store_manager_headers": build_user_headers("test-store-1", "StoreManager"),
}


def make_store_manager_headers(retailer_id: str) -> dict:
    """For StoreManager (entity_backed:Retailer). Pass the actual Retailer.id
    whenever the call is ownership-gated (read own store, create/submit/cancel
    a purchase order)."""
    return build_user_headers(retailer_id, "StoreManager")
