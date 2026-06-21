"""Pre-built role headers for every role in the PRD.

Five roles are opaque operator identities (InventoryClerk, SalesManager,
FinanceManager, ServiceAdvisor, TitleClerk): X-User-ID is logged but never
compared to a resource id, so the shared constant form is canonical for them.

The Customer role is entity_backed: X-User-ID must equal the acting Customer
record's id for ownership checks to pass, so it needs a per-instance builder.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "inventory_clerk_headers": build_user_headers("test-inventory-clerk-1", "InventoryClerk"),
    "sales_manager_headers": build_user_headers("test-sales-manager-1", "SalesManager"),
    "finance_manager_headers": build_user_headers("test-finance-manager-1", "FinanceManager"),
    "service_advisor_headers": build_user_headers("test-service-advisor-1", "ServiceAdvisor"),
    "title_clerk_headers": build_user_headers("test-title-clerk-1", "TitleClerk"),
    # Customer is entity_backed: this shared constant is a fallback for tests that
    # do NOT exercise ownership (e.g. an unauthenticated/bad-role probe). Ownership
    # tests MUST use make_customer_headers(customer_id) instead.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id
    as user_id whenever the call is ownership-gated (booking/cancelling own test
    drives, reading own record)."""
    return build_user_headers(user_id, "Customer")
