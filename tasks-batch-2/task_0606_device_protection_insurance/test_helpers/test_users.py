"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque operator roles — shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "claims_adjuster_headers": build_user_headers("test-adjuster-1", "ClaimsAdjuster"),
    "logistics_agent_headers": build_user_headers("test-logistics-1", "LogisticsAgent"),
    # entity_backed:Customer — shared constant is a fallback for non-ownership tests only.
    "subscriber_headers": build_user_headers("test-subscriber-1", "Subscriber"),
}


def make_subscriber_headers(customer_id: str) -> dict:
    """For Subscriber (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "Subscriber")
