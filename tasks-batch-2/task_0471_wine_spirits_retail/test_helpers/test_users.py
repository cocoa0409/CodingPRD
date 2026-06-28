"""Pre-built role headers for every role in the PRD (§2.1).

Customer is entity-backed: X-User-ID must equal the acting Customer's id for
ownership-gated calls. Use make_customer_headers(customer_id) in those cases.
StoreAssociate / ComplianceOfficer / Admin / Anonymous are opaque — the shared
constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# Customer ownership (e.g. 401/404/missing-payload cases).
TEST_USERS = {
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "store_associate_headers": build_user_headers("test-associate-1", "StoreAssociate"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For the entity-backed Customer role. Pass the actual Customer.id whenever
    the call is ownership-gated (orders, lines, club, special orders, scans)."""
    return build_user_headers(customer_id, "Customer")
