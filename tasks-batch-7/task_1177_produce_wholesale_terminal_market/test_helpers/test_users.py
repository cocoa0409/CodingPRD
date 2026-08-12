"""Pre-built role headers for every role declared in the PRD §2.1."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership. The CustomerRep constant is a FALLBACK for non-ownership paths only:
# CustomerRep is entity-backed, so any call that touches a customer-owned resource
# must instead use make_customer_rep_headers(customer_id) with the real id.
TEST_USERS = {
    "market_admin_headers": build_user_headers("test-market-admin-1", "MarketAdmin"),
    "receiver_headers": build_user_headers("test-receiver-1", "Receiver"),
    "usda_inspector_headers": build_user_headers("test-usda-inspector-1", "USDAInspector"),
    "sales_desk_headers": build_user_headers("test-sales-desk-1", "SalesDesk"),
    "billing_clerk_headers": build_user_headers("test-billing-clerk-1", "BillingClerk"),
    # entity_backed:Customer — fallback only; ownership-gated calls must build below.
    "customer_rep_headers": build_user_headers("test-customer-rep-1", "CustomerRep"),
}


def make_customer_rep_headers(customer_id: str) -> dict:
    """CustomerRep is entity-backed: X-User-ID must equal an existing Customer.id
    (PRD §2.1). Always pass the real customer id for ownership-gated calls."""
    return build_user_headers(customer_id, "CustomerRep")


# Short aliases used throughout fixtures and tests.
ADMIN_HEADERS = TEST_USERS["market_admin_headers"]
RECEIVER_HEADERS = TEST_USERS["receiver_headers"]
INSPECTOR_HEADERS = TEST_USERS["usda_inspector_headers"]
SALES_HEADERS = TEST_USERS["sales_desk_headers"]
BILLING_HEADERS = TEST_USERS["billing_clerk_headers"]
