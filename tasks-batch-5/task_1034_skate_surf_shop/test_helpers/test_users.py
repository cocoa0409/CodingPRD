"""Pre-built role headers for every role in the PRD (Section 2.1).

Three staff roles (ShopManager, BenchTech, SalesAssociate) are `opaque`:
X-User-ID is not tied to any persisted entity, so the shared constants are the
canonical form. The Customer role is entity_backed: for ownership-gated calls,
X-User-ID must equal the acting Customer's id — use make_customer_headers(id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for the three opaque staff roles, and a fallback
# for Customer only on non-ownership tests (e.g. plain reads / 404 checks).
TEST_USERS = {
    "shop_manager_headers": build_user_headers("test-shop-manager-1", "ShopManager"),
    "bench_tech_headers": build_user_headers("test-bench-tech-1", "BenchTech"),
    "sales_associate_headers": build_user_headers("test-sales-associate-1", "SalesAssociate"),
    # Customer is entity_backed; this shared value never equals a real Customer.id,
    # so it is only valid for tests that do not exercise a Customer ownership check.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id
    as user_id whenever the call is ownership-gated (accept/reject trade-in,
    approve/cancel special order, register/cancel event entry)."""
    return build_user_headers(user_id, "Customer")
