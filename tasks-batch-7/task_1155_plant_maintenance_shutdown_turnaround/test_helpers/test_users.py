"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "manager_headers": build_user_headers("tm-1", "TurnaroundManager"),
    "manager_headers_2": build_user_headers("tm-200", "TurnaroundManager"),
    "planner_headers": build_user_headers("planner-1", "Planner"),
    "coordinator_headers": build_user_headers("pc-1", "PermitCoordinator"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "supervisor_headers": build_user_headers("test-supervisor-1", "ContractorSupervisor"),
    "controller_headers": build_user_headers("cc-1", "CostController"),
    "controller_headers_2": build_user_headers("cc-9", "CostController"),
    "operations_headers": build_user_headers("ops-1", "OperationsRep"),
}


def make_supervisor_headers(user_id: str) -> dict:
    """For ContractorSupervisor (entity_backed:Contractor). Pass the actual
    Contractor.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "ContractorSupervisor")


def make_manager_headers(user_id: str) -> dict:
    """TurnaroundManager with an explicit opaque operator id (useful for SoD)."""
    return build_user_headers(user_id, "TurnaroundManager")


def make_controller_headers(user_id: str) -> dict:
    """CostController with an explicit opaque operator id (useful for SoD)."""
    return build_user_headers(user_id, "CostController")


def make_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Planner")


def make_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PermitCoordinator")


def make_operations_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OperationsRep")
