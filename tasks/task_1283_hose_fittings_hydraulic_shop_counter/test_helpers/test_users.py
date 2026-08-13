"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the four opaque operator roles, and as a fallback
# for the Customer role in tests that never exercise an ownership-gated call.
TEST_USERS = {
    "shop_manager_headers": build_user_headers("test-shop-manager-1", "ShopManager"),
    "counter_sales_headers": build_user_headers("test-counter-sales-1", "CounterSales"),
    "shop_technician_headers": build_user_headers("test-shop-technician-1", "ShopTechnician"),
    "field_technician_headers": build_user_headers("test-field-technician-1", "FieldTechnician"),
    # Customer is entity-backed: shared constant only for non-ownership tests.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For the Customer role, X-User-ID must be the acting Customer record's id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(customer_id, "Customer")
