"""Pre-built role headers for every role in the PRD.

All eight roles are opaque operator identities (PRD 2.1): X-User-ID is never
compared to any entity id and no resource is owned by its creator. The shared
constants below are therefore the canonical form for every call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "facility_admin_headers": build_user_headers("test-facility-admin-1", "FacilityAdmin"),
    "box_office_headers": build_user_headers("test-box-office-1", "BoxOfficeOperator"),
    "group_sales_headers": build_user_headers("test-group-sales-1", "GroupSalesAgent"),
    "membership_clerk_headers": build_user_headers("test-membership-clerk-1", "MembershipClerk"),
    "program_coordinator_headers": build_user_headers("test-program-coordinator-1", "ProgramCoordinator"),
    "events_manager_headers": build_user_headers("test-events-manager-1", "EventsManager"),
    "development_officer_headers": build_user_headers("test-development-officer-1", "DevelopmentOfficer"),
    "accessibility_headers": build_user_headers("test-accessibility-1", "AccessibilityCoordinator"),
}

# Anonymous header set carrying no auth headers — for the unauthenticated test.
NO_AUTH_HEADERS: dict = {"Content-Type": "application/json"}
