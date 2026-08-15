"""Pre-built role headers for every role in the PRD.

Opaque roles (BrokerOps, Inspector, FinanceAdmin) use shared constants.
Entity-backed roles (Seller, Customer) also get per-instance builders; any
ownership-gated call MUST use make_seller_headers(seller["id"]) /
make_customer_headers(customer["id"]) with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "broker_ops_headers": build_user_headers("test-broker-ops-1", "BrokerOps"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "finance_admin_headers": build_user_headers("test-finance-admin-1", "FinanceAdmin"),
    # Entity-backed fallbacks — only for tests that never exercise ownership.
    "seller_headers": build_user_headers("test-seller-1", "Seller"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_seller_headers(seller_id: str) -> dict:
    """Headers for the entity-backed Seller role. Pass the real Seller.id
    whenever the call is ownership-gated (offer create/cancel/read)."""
    return build_user_headers(seller_id, "Seller")


def make_customer_headers(customer_id: str) -> dict:
    """Headers for the entity-backed Customer role. Pass the real Customer.id
    whenever the call is ownership-gated (order create/deposit/cancel,
    return cases, order-scoped reads)."""
    return build_user_headers(customer_id, "Customer")
