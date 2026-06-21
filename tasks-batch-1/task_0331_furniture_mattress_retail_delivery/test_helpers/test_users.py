"""Pre-built role headers for every role in the PRD (Section 2.1).

SalesAssociate, StoreManager, and DeliveryDispatcher carry an opaque identity:
X-User-ID is an operator identifier never compared to any entity id, so the
shared TEST_USERS constants are the canonical form for them.

Customer is entity-backed (X-User-ID is the acting Customer.id). For any
ownership-gated Customer call (filing a return, listing own orders/plans), the
fixture MUST thread the real Customer.id through make_customer_headers(id) —
the shared constant below is only a non-owning fallback.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constant is the canonical form.
    "sales_associate_headers": build_user_headers("test-sales-1", "SalesAssociate"),
    "store_manager_headers": build_user_headers("test-manager-1", "StoreManager"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "DeliveryDispatcher"),
    # Entity-backed Customer — fallback only; ownership tests must use make_customer_headers.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id
    as user_id whenever the call is ownership-gated (return filing, own-order/plan
    listing)."""
    return build_user_headers(user_id, "Customer")


def make_sales_associate_headers(user_id: str) -> dict:
    """Opaque SalesAssociate identity with a caller-chosen operator id."""
    return build_user_headers(user_id, "SalesAssociate")
