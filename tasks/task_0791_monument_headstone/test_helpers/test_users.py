"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Admin, Designer, ShopManager, FieldOps),
# and for Customer-role tests that do NOT exercise ownership (e.g. 403/404 on foreign
# resources). Only the Customer role is entity_backed; ownership-gated Customer writes
# must use make_customer_headers(customer_id) with the real Customer.id.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "designer_headers": build_user_headers("test-designer-1", "Designer"),
    "shop_manager_headers": build_user_headers("test-shop-1", "ShopManager"),
    "field_ops_headers": build_user_headers("test-fieldops-1", "FieldOps"),
    # Shared Customer constant — fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (cancel, payment, approve/request-changes,
    restoration request)."""
    return build_user_headers(user_id, "Customer")


def admin_headers() -> dict:
    return TEST_USERS["admin_headers"]


def designer_headers() -> dict:
    return TEST_USERS["designer_headers"]


def shop_manager_headers() -> dict:
    return TEST_USERS["shop_manager_headers"]


def field_ops_headers() -> dict:
    return TEST_USERS["field_ops_headers"]
