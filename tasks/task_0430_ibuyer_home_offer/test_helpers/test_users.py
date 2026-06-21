"""Pre-built role headers for every role in the iBuyer Home Offer PRD (§2.1).

There are exactly three roles: Seller, PricingAnalyst, OperationsAdmin.

- `Seller` is **entity-backed** (PRD §2.1): when X-User-Role is `Seller`, X-User-ID
  is the `id` of the acting Seller record, and ownership checks compare the underlying
  Property.seller_id against this value. Ownership-gated Seller calls (accept, withdraw,
  schedule-close, cancel) MUST use make_seller_headers(<the real Seller.id>) — the
  shared constant below is a fallback for non-ownership tests only.
- `PricingAnalyst` and `OperationsAdmin` are **opaque** operator identities: the server
  never compares their X-User-ID to any entity id. The shared constants are the
  canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise ownership.
TEST_USERS = {
    # entity_backed:Seller — shared constant is a fallback for non-ownership tests only.
    "seller_headers": build_user_headers("test-seller-1", "Seller"),
    # opaque operator roles — shared constant is the canonical form.
    "pricing_analyst_headers": build_user_headers("test-analyst-1", "PricingAnalyst"),
    "operations_admin_headers": build_user_headers("test-ops-1", "OperationsAdmin"),
}


def make_seller_headers(user_id: str) -> dict:
    """For Seller (entity_backed:Seller). Pass the actual Seller.id as user_id whenever
    the call is ownership-gated (PRD §2.1), so the underlying Property.seller_id ==
    X-User-ID ownership check passes."""
    return build_user_headers(user_id, "Seller")


def make_pricing_analyst_headers(user_id: str = "test-analyst-1") -> dict:
    return build_user_headers(user_id, "PricingAnalyst")


def make_operations_admin_headers(user_id: str = "test-ops-1") -> dict:
    return build_user_headers(user_id, "OperationsAdmin")
