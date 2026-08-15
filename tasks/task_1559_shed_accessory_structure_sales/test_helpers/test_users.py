"""Pre-built role headers for every role in the PRD (§2.1).

Customer is entity-backed: for ownership-gated calls use make_customer_headers()
with the actual Customer.id. The shared customer_headers constant is only a
fallback for tests that do not exercise ownership (e.g., role-not-permitted).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque staff roles: the X-User-ID is not tied to any persisted entity.
    "sales_rep_headers": build_user_headers("test-salesrep-1", "SalesRep"),
    "permit_coordinator_headers": build_user_headers("test-permitco-1", "PermitCoordinator"),
    "install_crew_headers": build_user_headers("test-crew-1", "InstallCrew"),
    "finance_manager_headers": build_user_headers("test-finance-1", "FinanceManager"),
    "operations_admin_headers": build_user_headers("test-opsadmin-1", "OperationsAdmin"),
    # Entity-backed role: fallback constant for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """Customer is entity-backed (PRD §2.1): X-User-ID must be the Customer.id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")
