"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for entity-backed roles in tests
# that do not exercise ownership (404 / 400 / role-only checks).
TEST_USERS = {
    "ehs_admin_headers": build_user_headers("test-ehs-admin-1", "EHSAdministrator"),
    "vending_tech_headers": build_user_headers("test-vending-tech-1", "VendingTechnician"),
    "safety_officer_headers": build_user_headers("test-safety-officer-1", "SafetyOfficer"),
    "finance_analyst_headers": build_user_headers("test-finance-analyst-1", "FinanceAnalyst"),
    "compliance_auditor_headers": build_user_headers("test-compliance-auditor-1", "ComplianceAuditor"),
    # Entity-backed roles: shared constants are fallbacks for non-ownership tests
    # only. For any call where the server compares X-User-ID to a stored Employee
    # (vend, grant override, reverse vend, dispute batch), the caller MUST build
    # headers with the actual employee id via make_employee_headers / make_manager_headers.
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    # Any: shared read surface.
    "any_headers": build_user_headers("test-any-1", "Any"),
}


def make_employee_headers(user_id: str) -> dict:
    """For Employee (entity-backed: Employee). Pass the actual Employee.id
    whenever the call binds the caller to a persisted Employee row (vend)."""
    return build_user_headers(user_id, "Employee")


def make_manager_headers(user_id: str) -> dict:
    """For Manager (entity-backed: Employee with is_manager == true). Pass the
    actual Employee.id whenever the call is ownership-gated or segregated
    (grant/revoke override, reverse vend, dispute batch)."""
    return build_user_headers(user_id, "Manager")
