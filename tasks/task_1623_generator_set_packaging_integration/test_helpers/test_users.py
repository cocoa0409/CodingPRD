"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (all roles except CustomerContact),
# and for tests that don't exercise ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "sales_engineer_headers": build_user_headers("test-sales-1", "SalesEngineer"),
    "application_engineer_headers": build_user_headers("test-app-1", "ApplicationEngineer"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "test_engineer_headers": build_user_headers("test-eng-1", "TestEngineer"),
    "logistics_coordinator_headers": build_user_headers("test-logistics-1", "LogisticsCoordinator"),
    "field_service_manager_headers": build_user_headers("test-fsm-1", "FieldServiceManager"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_contact_headers": build_user_headers("test-customer-1", "CustomerContact"),
}


# Per-instance builder — required for the entity_backed role CustomerContact.
def make_customer_contact_headers(customer_account_id: str) -> dict:
    """For CustomerContact (entity_backed: CustomerAccount). Pass the actual
    CustomerAccount.id whenever the call is ownership-gated (commissioning accept)."""
    return build_user_headers(customer_account_id, "CustomerContact")


def make_test_engineer_headers(user_id: str) -> dict:
    """Distinct TestEngineer identities for segregation-of-duties tests
    (recorder vs acceptor)."""
    return build_user_headers(user_id, "TestEngineer")
