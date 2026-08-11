"""Pre-built role headers for every role in the PRD (Section 2.1).

Shared constants are safe for the opaque roles (Anonymous, Agronomist,
FulfillmentOps, PlatformAdmin) and for Customer calls whose outcome does not
depend on owning the subject resource. For ownership-gated Customer calls,
always build per-instance headers with make_customer_headers(entity_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque role — canonical shared form
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    # entity_backed:Customer — fallback ONLY for non-ownership probes
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles — canonical shared forms
    "agronomist_headers": build_user_headers("test-agronomist-1", "Agronomist"),
    "fulfillment_ops_headers": build_user_headers("test-fulfillment-ops-1", "FulfillmentOps"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")
