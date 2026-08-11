"""Pre-built role headers for every role in PRD §2.1.

All roles in this API are opaque: `X-User-ID` is an operator identifier never
compared to any entity's `id`, so shared constants are canonical for all roles.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "intake_coordinator_headers": build_user_headers("test-intake-1", "IntakeCoordinator"),
    "assessor_headers": build_user_headers("test-assessor-1", "Assessor"),
    "project_manager_headers": build_user_headers("test-pm-1", "ProjectManager"),
    "funding_coordinator_headers": build_user_headers("test-fc-1", "FundingCoordinator"),
    "crew_lead_headers": build_user_headers("test-crew-1", "CrewLead"),
    "logistics_coordinator_headers": build_user_headers("test-logistics-1", "LogisticsCoordinator"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "billing_coordinator_headers": build_user_headers("test-billing-1", "BillingCoordinator"),
    "client_headers": build_user_headers("test-client-1", "Client"),
    "system_admin_headers": build_user_headers("test-sysadmin-1", "SystemAdmin"),
}
