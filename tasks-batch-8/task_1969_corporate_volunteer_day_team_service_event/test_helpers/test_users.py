"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
# The community engagement manager handle "cem-1" is recorded as created_by_user_id
# on procurement orders it creates; the segregation-of-duties checks key off it.
TEST_USERS = {
    "cem_headers": build_user_headers("cem-1", "CommunityEngagementManager"),
    "cem_alt_headers": build_user_headers("cem-2", "CommunityEngagementManager"),
    "procurement_officer_headers": build_user_headers("po-1", "ProcurementOfficer"),
    "procurement_officer_creator_headers": build_user_headers("cem-1", "ProcurementOfficer"),
    "logistics_headers": build_user_headers("lc-1", "LogisticsCoordinator"),
    "finance_headers": build_user_headers("fc-1", "FinanceController"),
    "platform_admin_headers": build_user_headers("pa-1", "PlatformAdmin"),
    "any_headers": build_user_headers("any-1", "Any"),
    # Fallback constants for entity-backed roles; only for calls whose success
    # does not depend on the caller owning the subject resource.
    "volunteer_headers": build_user_headers("test-volunteer-1", "EmployeeVolunteer"),
    "staff_lead_headers": build_user_headers("test-lead-1", "StaffLead"),
    "coordinator_headers": build_user_headers("test-nonprofit-1", "NonprofitCoordinator"),
}


def make_employee_volunteer_headers(user_id: str) -> dict:
    """For EmployeeVolunteer (entity-backed). Pass the actual EmployeeVolunteer.id
    whenever the call is ownership-gated (register, sign-waiver, cancel, survey)."""
    return build_user_headers(user_id, "EmployeeVolunteer")


def make_staff_lead_headers(user_id: str) -> dict:
    """For StaffLead (entity-backed). Pass the actual EmployeeVolunteer.id
    whenever the call is ownership-gated (check-in, withdraw own assignment)."""
    return build_user_headers(user_id, "StaffLead")


def make_nonprofit_coordinator_headers(user_id: str) -> dict:
    """For NonprofitCoordinator (entity-backed). Pass the actual NonprofitPartner.id
    whenever the call is ownership-gated (project create, impact create, resubmit)."""
    return build_user_headers(user_id, "NonprofitCoordinator")
