"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles (CrewCaller, CrewManager), and for
# Employee-role calls whose outcome does not depend on owning the target resource
# (e.g., 400-on-bad-payload or role-rejection probes).
TEST_USERS = {
    # entity_backed role: fallback for non-ownership tests only.
    "employee_headers": build_user_headers("test-employee-shared", "Employee"),
    # opaque roles: shared constants are canonical.
    "crew_caller_headers": build_user_headers("test-crew-caller-1", "CrewCaller"),
    "crew_manager_headers": build_user_headers("test-crew-manager-1", "CrewManager"),
}


def make_employee_headers(user_id: str) -> dict:
    """For Employee (entity_backed:Employee). Pass the actual Employee.id as
    user_id whenever the call is ownership-gated (mark-up, lay-off, call
    accept/decline, assignment on-duty/tie-up/lay-off, pay submit/resubmit,
    leave cancel)."""
    return build_user_headers(user_id, "Employee")


def make_crew_caller_headers(user_id: str = "test-crew-caller-1") -> dict:
    return build_user_headers(user_id, "CrewCaller")


def make_crew_manager_headers(user_id: str = "test-crew-manager-1") -> dict:
    return build_user_headers(user_id, "CrewManager")
