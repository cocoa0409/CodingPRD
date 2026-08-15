"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise
# ownership. The Customer role is entity_backed: use make_customer_headers()
# with the real Customer.id whenever the call is ownership-gated (quote
# accept/reject, customer-side punch item creation, customer-scoped GETs).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "project_manager_headers": build_user_headers("test-pm-1", "ProjectManager"),
    "kitchen_designer_headers": build_user_headers("test-kd-1", "KitchenDesigner"),
    "sales_rep_headers": build_user_headers("test-sr-1", "SalesRep"),
    "permit_coordinator_headers": build_user_headers(
        "test-pc-1", "PermitCoordinator"
    ),
    "fabrication_lead_headers": build_user_headers("test-fl-1", "FabricationLead"),
    "logistics_coordinator_headers": build_user_headers(
        "test-lc-1", "LogisticsCoordinator"
    ),
    "startup_technician_headers": build_user_headers(
        "test-st-1", "StartupTechnician"
    ),
    "service_manager_headers": build_user_headers("test-sm-1", "ServiceManager"),
    # Fallback only for non-ownership tests (e.g., role-existence checks).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """Customer role is entity-backed: X-User-ID must equal the Customer.id
    for any ownership-gated call (accept/reject quote, raise punch item)."""
    return build_user_headers(customer_id, "Customer")
