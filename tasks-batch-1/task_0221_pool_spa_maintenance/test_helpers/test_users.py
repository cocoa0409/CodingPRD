"""Pre-built role headers for every role in the PRD (§2.1).

Three roles are operator-style / opaque (AccountManager, RouteManager,
FieldTechnician): their X-User-ID is never compared to any entity id, so the
shared constant is always the canonical form. The fourth role (Customer) is
entity_backed:Customer — ownership checks compare X-User-ID to the owning
Customer.id, so ownership-gated Customer calls MUST use make_customer_headers()
with the real Customer id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — shared constants are the canonical form.
    "account_manager_headers": build_user_headers("test-account-manager-1", "AccountManager"),
    "route_manager_headers": build_user_headers("test-route-manager-1", "RouteManager"),
    "field_technician_headers": build_user_headers("test-field-technician-1", "FieldTechnician"),
    # entity_backed:Customer — shared constant is a fallback for non-ownership
    # tests only (e.g. a 404/missing-resource or a non-owner negative test).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (hold / resolve on a work
    order whose pool the customer owns)."""
    return build_user_headers(user_id, "Customer")
