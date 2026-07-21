"""Pre-built role headers for every role in the PRD (§2.1).

Customer is entity_backed:Member — for any ownership-gated call, headers MUST be built
with the acting Member's real id via make_customer_headers(member_id). The shared
TEST_USERS["customer_headers"] constant is a fallback for tests that never exercise ownership
(e.g. unauthenticated/unauthorized/validation checks). The other four roles are opaque
operator identities the server never compares to an entity id, so shared constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "shop_staff_headers": build_user_headers("staff-1", "ShopStaff"),
    "inventory_manager_headers": build_user_headers("inventory-1", "InventoryManager"),
    "wholesale_approver_headers": build_user_headers("approver-1", "WholesaleApprover"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
}


def make_customer_headers(member_id: str) -> dict:
    """Headers for the Customer acting as Member `member_id`. Pass the real Member.id
    on every ownership-gated Customer call (orders, subscriptions, sessions, wholesale)."""
    return build_user_headers(member_id, "Customer")
