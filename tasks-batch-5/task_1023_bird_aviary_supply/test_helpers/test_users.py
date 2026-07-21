"""Pre-built role headers for every role in the PRD.

Customer is entity-backed: ownership checks compare a resource's customer_id
to X-User-ID, so ownership-gated Customer calls MUST use make_customer_headers()
with the actual Customer.id. The other three roles are opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Customer tests that do not
# exercise ownership (e.g., 400-on-bad-payload, 403-forbidden-role).
TEST_USERS = {
    "store_manager_headers": build_user_headers("test-store-manager-1", "StoreManager"),
    "aviary_staff_headers": build_user_headers("test-aviary-staff-1", "AviaryStaff"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    # entity_backed fallback: only for non-ownership Customer tests.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id
    as user_id whenever the call is ownership-gated (subscriptions, boarding,
    grooming, special-orders)."""
    return build_user_headers(user_id, "Customer")
