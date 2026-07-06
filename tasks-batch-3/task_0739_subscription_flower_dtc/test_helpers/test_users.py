"""Pre-built role headers for every role in the PRD.

Customer is entity_backed:Customer — ownership-gated calls MUST use make_customer_headers(customer["id"]).
FulfillmentOps, BillingAdmin, PlatformAdmin are opaque — a shared constant is the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for non-ownership tests.
TEST_USERS = {
    # entity_backed role: shared fallback ONLY for non-ownership calls (e.g., a distinct-actor case).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles: shared constants are canonical.
    "fulfillment_ops_headers": build_user_headers("test-ops-1", "FulfillmentOps"),
    "billing_admin_headers": build_user_headers("test-billing-1", "BillingAdmin"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


# Per-instance builders — required for every entity_backed role.
def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (pause/resume/change/cancel/skip/redeem/cancel-preview/wallet)."""
    return build_user_headers(user_id, "Customer")


def make_fulfillment_ops_headers(operator_id: str = "test-ops-1") -> dict:
    """For FulfillmentOps (opaque). Any opaque id works; PRD says the server does not compare it to any entity."""
    return build_user_headers(operator_id, "FulfillmentOps")


def make_billing_admin_headers(operator_id: str = "test-billing-1") -> dict:
    """For BillingAdmin (opaque)."""
    return build_user_headers(operator_id, "BillingAdmin")


def make_platform_admin_headers(operator_id: str = "test-admin-1") -> dict:
    """For PlatformAdmin (opaque)."""
    return build_user_headers(operator_id, "PlatformAdmin")


def anonymous_headers() -> dict:
    """No X-User-Role / X-User-ID headers — for testing ERR_UNAUTHENTICATED."""
    return {"Content-Type": "application/json"}
