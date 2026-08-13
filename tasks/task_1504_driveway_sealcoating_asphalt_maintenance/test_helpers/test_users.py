"""Pre-built role headers for every role in the PRD (§2.1).

Staff roles (OfficeAdmin, Estimator, Dispatcher, CrewLead) use opaque operator
identifiers. The Customer role is entity-backed: when a call is ownership-gated,
X-User-ID must equal the owning Customer entity's id — use
make_customer_headers(customer["id"]) for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque staff roles, and for Customer calls whose
# success does NOT depend on owning the subject resource.
TEST_USERS = {
    "office_admin_headers": build_user_headers("admin-1", "OfficeAdmin"),
    "estimator_headers": build_user_headers("estimator-1", "Estimator"),
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "crew_lead_headers": build_user_headers("crew-lead-1", "CrewLead"),
    # Fallback only for non-ownership tests (e.g., role-denial probes).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """Customer is entity-backed: pass the actual Customer.id for
    ownership-gated calls (quote accept/decline/revision, invoice pay,
    warranty claim filing)."""
    return build_user_headers(customer_id, "Customer")


def make_office_admin_headers(user_id: str) -> dict:
    """OfficeAdmin with a specific operator id — needed when the workflow
    records the admin identity (e.g., warranty investigation segregation)."""
    return build_user_headers(user_id, "OfficeAdmin")
