"""Pre-built role headers for every role in the PRD (§2.1).

For the opaque operator roles (OpsAdmin, Dispatcher, Driver, BillingAdmin) the
shared constants are the canonical form — their X-User-ID is never compared to
any entity id.

For CustomerSelf, X-User-ID IS the acting customer's id (entity-backed), so any
ownership-gated call MUST use make_customer_self_headers(customer["id"]). The
shared `customer_self_headers` constant is a fallback for tests whose outcome
does not depend on owning the subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
    "billing_admin_headers": build_user_headers("test-billing-admin-1", "BillingAdmin"),
    # Fallback only: non-ownership checks (e.g. creating a work order where the
    # body names the customer). Never use for ownership-gated reads/actions.
    "customer_self_headers": build_user_headers("test-customer-self-1", "CustomerSelf"),
}


def make_customer_self_headers(customer_id: str) -> dict:
    """CustomerSelf is entity-backed: pass the actual Customer.id whenever the
    call is ownership-gated (PRD §2.1)."""
    return build_user_headers(customer_id, "CustomerSelf")
