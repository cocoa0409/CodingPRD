"""Pre-built role headers for every role in the PRD.

Trader, SalesAgent, and ComplianceOfficer carry an OPAQUE identity — the
X-User-ID is not tied to any persisted entity, so the shared constant is
the canonical form. The Customer role is ENTITY_BACKED:Customer — ownership
checks compare a layaway's customer_id to X-User-ID, so any ownership-gated
Customer call MUST use make_customer_headers(customer_id) with the real id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is canonical.
    "trader_headers": build_user_headers("test-trader-1", "Trader"),
    "sales_agent_headers": build_user_headers("test-sales-agent-1", "SalesAgent"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    # entity_backed Customer — shared constant is a fallback for
    # non-ownership tests only (never for a real ownership-gated deposit/cancel).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual
    Customer.id as user_id whenever the call is ownership-gated
    (POST /layaways/{id}/deposit, POST /layaways/{id}/cancel)."""
    return build_user_headers(user_id, "Customer")
