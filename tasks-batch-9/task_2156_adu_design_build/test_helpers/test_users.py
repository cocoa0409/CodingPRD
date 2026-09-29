"""Pre-built role headers for every role in the PRD (§2.1).

Five roles carry opaque identity — PlatformAdmin, DesignLead, PlanChecker,
ProjectManager and FinanceAdvisor — so the shared constants below are the
canonical form for them.

Two roles are entity-backed and MUST use the per-instance builders:
  * Homeowner       — X-User-ID is the id of the acting Property.
  * BuildingInspector — X-User-ID is the id of the acting Inspector.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "design_lead_headers": build_user_headers("test-design-lead-1", "DesignLead"),
    "plan_checker_headers": build_user_headers("test-plan-checker-1", "PlanChecker"),
    "project_manager_headers": build_user_headers("test-project-manager-1", "ProjectManager"),
    "finance_advisor_headers": build_user_headers("test-finance-advisor-1", "FinanceAdvisor"),
    # Entity-backed roles: these shared constants are only safe for tests that
    # never reach an ownership check (role-level 403s, unknown-id 404s).
    "homeowner_headers": build_user_headers("test-homeowner-1", "Homeowner"),
    "building_inspector_headers": build_user_headers("test-inspector-1", "BuildingInspector"),
}

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
DESIGN_LEAD = TEST_USERS["design_lead_headers"]
PLAN_CHECKER = TEST_USERS["plan_checker_headers"]
PROJECT_MANAGER = TEST_USERS["project_manager_headers"]
FINANCE_ADVISOR = TEST_USERS["finance_advisor_headers"]


def make_homeowner_headers(property_id: str) -> dict:
    """Homeowner headers. X-User-ID is the id of the Property they own, so every
    ownership-gated call must pass the actual parcel id."""
    return build_user_headers(property_id, "Homeowner")


def make_building_inspector_headers(inspector_id: str) -> dict:
    """BuildingInspector headers. X-User-ID is the id of the Inspector row the
    appointment was booked to."""
    return build_user_headers(inspector_id, "BuildingInspector")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_design_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DesignLead")


def make_plan_checker_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlanChecker")


def make_project_manager_headers(user_id: str) -> dict:
    """ProjectManager headers with an explicit operator id — the id is recorded
    on a change order as decided_by_user_id."""
    return build_user_headers(user_id, "ProjectManager")


def make_finance_advisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceAdvisor")
