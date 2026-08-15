"""Pre-built role headers for every role in the PRD (§2.1).

CustomerAdmin is entity-backed: its X-User-ID must be the acting Customer's id
for any ownership-gated call. The other four roles carry opaque operator ids.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, admin-acted calls).
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_admin_headers": build_user_headers("test-customer-admin-1", "CustomerAdmin"),
    # opaque roles: shared constants are the canonical form.
    "warehouse_operator_headers": build_user_headers("op-1", "WarehouseOperator"),
    "quality_manager_headers": build_user_headers("qm-1", "QualityManager"),
    "claims_adjuster_headers": build_user_headers("ca-1", "ClaimsAdjuster"),
    "billing_admin_headers": build_user_headers("ba-1", "BillingAdmin"),
}


def make_customer_admin_headers(customer_id: str) -> dict:
    """For CustomerAdmin (entity-backed by Customer). Pass the actual Customer.id
    whenever the call is ownership-gated (receipts, orders, claims, disputes)."""
    return build_user_headers(customer_id, "CustomerAdmin")


def make_warehouse_operator_headers(user_id: str = "op-1") -> dict:
    return build_user_headers(user_id, "WarehouseOperator")


def make_quality_manager_headers(user_id: str = "qm-1") -> dict:
    return build_user_headers(user_id, "QualityManager")


def make_claims_adjuster_headers(user_id: str = "ca-1") -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_billing_admin_headers(user_id: str = "ba-1") -> dict:
    return build_user_headers(user_id, "BillingAdmin")
