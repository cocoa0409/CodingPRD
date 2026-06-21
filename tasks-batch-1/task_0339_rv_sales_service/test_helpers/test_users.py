"""Pre-built role headers for every role in the PRD (§2.1).

The three operator roles — DealerManager, SalesAgent, ServiceAdvisor — carry an
opaque X-User-ID that the server never compares against any entity id, so a
shared-constant header is the canonical form for each.

The Customer role is entity-backed: X-User-ID must equal the acting Customer
record's id. Ownership-gated reads therefore require make_customer_headers with
the real Customer.id; the shared constant is only a fallback for tests that do
not exercise customer ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "dealer_manager_headers": build_user_headers("test-manager-1", "DealerManager"),
    "sales_agent_headers": build_user_headers("test-sales-1", "SalesAgent"),
    "service_advisor_headers": build_user_headers("test-service-1", "ServiceAdvisor"),
    # Fallback constant — only for non-ownership Customer tests (403/forbidden).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the entity-backed Customer role. Pass the actual Customer.id as user_id
    whenever a read is ownership-gated."""
    return build_user_headers(user_id, "Customer")
