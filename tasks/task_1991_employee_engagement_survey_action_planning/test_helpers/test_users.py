"""Pre-built role headers for every role in the PRD (§2.1).

Identity rules:
- HRAdmin / PeopleAnalyst / Executive: opaque operator ids, never compared
  against entity ids. Shared constants are canonical.
- UnitManager: entity-backed by OrgUnit.manager_user_id — X-User-ID must equal
  the unit's manager_user_id string. Use make_unit_manager_headers() with the
  unit's manager_user_id for ownership-gated calls.
- EmployeeRole: entity-backed by Employee — X-User-ID must equal the Employee's
  id. Use make_employee_headers(employee["id"]) for ownership-gated calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, etc.).
TEST_USERS = {
    "hr_admin_headers": build_user_headers("test-hr-admin-1", "HRAdmin"),
    "people_analyst_headers": build_user_headers("test-people-analyst-1", "PeopleAnalyst"),
    "executive_headers": build_user_headers("test-executive-1", "Executive"),
    # Fallbacks for non-ownership tests only; ownership-gated calls MUST use
    # the per-instance builders below.
    "unit_manager_headers": build_user_headers("test-unit-manager-1", "UnitManager"),
    "employee_role_headers": build_user_headers("test-employee-1", "EmployeeRole"),
}


def make_hr_admin_headers(user_id: str = "test-hr-admin-1") -> dict:
    """HRAdmin is opaque; a distinct id per operator is supported."""
    return build_user_headers(user_id, "HRAdmin")


def make_people_analyst_headers(user_id: str = "test-people-analyst-1") -> dict:
    """PeopleAnalyst is opaque; a distinct id per operator is supported."""
    return build_user_headers(user_id, "PeopleAnalyst")


def make_executive_headers(user_id: str = "test-executive-1") -> dict:
    """Executive is opaque; a distinct id per operator is supported."""
    return build_user_headers(user_id, "Executive")


def make_unit_manager_headers(user_id: str) -> dict:
    """UnitManager identity is the OrgUnit.manager_user_id of the managed unit.
    Pass the unit's manager_user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "UnitManager")


def make_employee_headers(user_id: str) -> dict:
    """EmployeeRole identity is the Employee.id. Pass the actual employee id
    whenever the call is ownership-gated (submit, read own invite/response)."""
    return build_user_headers(user_id, "EmployeeRole")
