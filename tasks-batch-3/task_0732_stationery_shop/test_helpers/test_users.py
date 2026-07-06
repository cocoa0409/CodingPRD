"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe only for opaque ShopAdmin, and for tests that never exercise
# ownership on Customer/Designer. For any ownership-gated call, use make_customer_headers
# or make_designer_headers with the real entity id.
TEST_USERS = {
    "shop_admin_headers": build_user_headers("test-shop-admin-1", "ShopAdmin"),
    # Fallback constants for negative tests where the acting user id is deliberately
    # a non-existent id or is irrelevant to ownership (e.g., 400 on bad payload).
    "customer_headers": build_user_headers("test-customer-fallback", "Customer"),
    "designer_headers": build_user_headers("test-designer-fallback", "Designer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the real Customer.id whenever
    the call is ownership-gated (design/order/proof actions on the customer's own
    resources)."""
    return build_user_headers(user_id, "Customer")


def make_designer_headers(user_id: str) -> dict:
    """For Designer (entity_backed:Designer). Pass the real Designer.id whenever
    the call is ownership-gated (submit-proof on the designer's own proof)."""
    return build_user_headers(user_id, "Designer")


def make_shop_admin_headers(user_id: str = "test-shop-admin-1") -> dict:
    """ShopAdmin is opaque — the user_id is not tied to any entity."""
    return build_user_headers(user_id, "ShopAdmin")
