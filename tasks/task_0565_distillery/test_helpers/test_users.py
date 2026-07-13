"""Pre-built role headers for every role in the PRD (2.1).

The four operator roles (ProductionManager, ComplianceOfficer, SalesManager,
TastingRoomStaff) carry an opaque X-User-ID that the server never compares to any
entity id, so their shared constants are always safe. The Customer role is
entity_backed: its X-User-ID must equal the acting Customer.id, so ownership-gated
Customer calls MUST use make_customer_headers(customer_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "production_headers": build_user_headers("op-pm-1", "ProductionManager"),
    "compliance_headers": build_user_headers("op-oc-1", "ComplianceOfficer"),
    "sales_headers": build_user_headers("op-sm-1", "SalesManager"),
    "tasting_headers": build_user_headers("op-trs-1", "TastingRoomStaff"),
    # Customer shared constant: use ONLY for non-ownership tests (e.g. RBAC 403 on a
    # foreign order). Ownership-gated Customer calls must use make_customer_headers().
    "customer_headers": build_user_headers("test-customer-unused", "Customer"),
    # No X-User-Role header -> ERR_UNAUTHENTICATED.
    "anonymous_headers": {"Content-Type": "application/json"},
}


def make_customer_headers(user_id: str) -> dict:
    """For the entity_backed Customer role. Pass the acting Customer.id as user_id
    whenever the call is ownership-gated (own sales orders / tour bookings)."""
    return build_user_headers(user_id, "Customer")
