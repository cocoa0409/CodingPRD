"""Pre-built role headers for every role in PRD §2.1.

Customer is entity-backed: X-User-ID must be the acting CustomerAccount's id
for ownership-gated calls, so use make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "quote_agent_headers": build_user_headers("test-quote-agent-1", "QuoteAgent"),
    "dispatch_manager_headers": build_user_headers("test-dispatch-1", "DispatchManager"),
    "fleet_manager_headers": build_user_headers("test-fleet-1", "FleetManager"),
    "safety_officer_headers": build_user_headers("test-safety-1", "SafetyOfficer"),
    "compliance_officer_headers": build_user_headers("test-compliance-1",
                                                     "ComplianceOfficer"),
    # entity_backed role: fallback ONLY for tests that do not exercise ownership.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed: CustomerAccount). Pass the actual
    CustomerAccount.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")
