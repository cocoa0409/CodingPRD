"""Pre-built role headers for every role in the PRD.

Three operator roles (StoreManager, Cashier, InventoryClerk) carry an opaque
X-User-ID that the server records but never compares to an entity id, so a shared
constant is the canonical form for them.

Customer is entity_backed:LoyaltyAccount — when X-User-Role is Customer, X-User-ID
is the id of the acting LoyaltyAccount, and ownership checks compare a resource's
loyalty foreign key to X-User-ID. Ownership-gated Customer calls MUST therefore use
make_customer_headers(loyalty_account_id) with the real account id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that do not exercise
# Customer ownership (e.g. 400/404/403 negative checks).
TEST_USERS = {
    "store_manager_headers": build_user_headers("test-store-manager-1", "StoreManager"),
    "cashier_headers": build_user_headers("test-cashier-1", "Cashier"),
    "inventory_clerk_headers": build_user_headers("test-inventory-clerk-1", "InventoryClerk"),
    # Customer fallback: a non-resolving id, valid only for non-ownership negative tests.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(loyalty_account_id: str) -> dict:
    """For the Customer role (entity_backed:LoyaltyAccount). Pass the actual
    LoyaltyAccount.id as user_id whenever the call is ownership-gated (reading the
    member's own account, layaways, or sales)."""
    return build_user_headers(loyalty_account_id, "Customer")
