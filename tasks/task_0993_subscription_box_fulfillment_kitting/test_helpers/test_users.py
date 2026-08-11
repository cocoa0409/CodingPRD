"""Pre-built role headers for every role in the PRD (§2.1).

ClientOps is entity-backed: its X-User-ID must be the acting Client's id.
Use make_client_ops_headers(client_id) for every ownership-gated call.
The shared TEST_USERS["client_ops_headers"] entry is only safe for tests that
do not depend on the caller owning the subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "warehouse_ops_headers": build_user_headers("test-warehouse-ops-1", "WarehouseOps"),
    "billing_admin_headers": build_user_headers("test-billing-admin-1", "BillingAdmin"),
    "customer_service_headers": build_user_headers("test-customer-service-1", "CustomerService"),
    # Entity-backed role fallback — non-ownership tests only.
    "client_ops_headers": build_user_headers("test-client-ops-1", "ClientOps"),
}


def make_client_ops_headers(client_id: str) -> dict:
    """ClientOps is entity-backed by Client. Pass the actual Client.id as
    client_id whenever the call is ownership-gated (plans, subscribers,
    import batches, statements of that client)."""
    return build_user_headers(client_id, "ClientOps")
