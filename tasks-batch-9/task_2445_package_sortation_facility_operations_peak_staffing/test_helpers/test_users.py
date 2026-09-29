"""Header bundles for the six roles (PRD §2.1).

Two families of helper live here and the difference is load-bearing.

`TEST_USERS` holds one ready-made header bundle per role, usable whenever the
caller's identity does not matter. The five operator roles (`FacilityAdmin`,
`InboundCoordinator`, `SortSupervisor`, `LaborPlanner`, `OpsManager`) carry an
opaque `X-User-ID` that the server never compares to any entity, so the shared
constant is always fine for them.

`make_worker_headers(worker_id)` exists because the `Worker` role is different:
`X-User-ID` is the `id` of the acting `Worker` row, and ownership checks compare
the resource's `worker_id` to it. A `Worker` request must therefore always be
built per worker; the shared `TEST_USERS["worker"]` bundle names no real worker
and is only useful for provoking the ownership failure itself.

Separate operator identities are also provided because segregation of duties on
the shift-plan approval fork is a string comparison between the approver's
`X-User-ID` and the plan's stored `submitted_by_user_id`.
"""

from prd_bench_local_runner.testing import build_user_headers


# ─── Opaque operator identifiers ──────────────────────
FACILITY_ADMIN_USER_ID = "operator-facility-admin-1"
INBOUND_COORDINATOR_USER_ID = "operator-inbound-coordinator-1"
SORT_SUPERVISOR_USER_ID = "operator-sort-supervisor-1"
LABOR_PLANNER_USER_ID = "operator-labor-planner-1"
OPS_MANAGER_USER_ID = "operator-ops-manager-1"

# Second identities within the same role, for the segregation-of-duties fork.
LABOR_PLANNER_2_USER_ID = "operator-labor-planner-2"
OPS_MANAGER_2_USER_ID = "operator-ops-manager-2"

# A placeholder worker identity that intentionally matches no persisted worker.
UNKNOWN_WORKER_USER_ID = "00000000-0000-0000-0000-000000000000"


# ─── Role names, spelled exactly as the PRD spells them ───
ROLE_FACILITY_ADMIN = "FacilityAdmin"
ROLE_INBOUND_COORDINATOR = "InboundCoordinator"
ROLE_SORT_SUPERVISOR = "SortSupervisor"
ROLE_LABOR_PLANNER = "LaborPlanner"
ROLE_OPS_MANAGER = "OpsManager"
ROLE_WORKER = "Worker"

ALL_ROLES = [
    ROLE_FACILITY_ADMIN,
    ROLE_INBOUND_COORDINATOR,
    ROLE_SORT_SUPERVISOR,
    ROLE_LABOR_PLANNER,
    ROLE_OPS_MANAGER,
    ROLE_WORKER,
]

OPERATOR_ROLES = [
    ROLE_FACILITY_ADMIN,
    ROLE_INBOUND_COORDINATOR,
    ROLE_SORT_SUPERVISOR,
    ROLE_LABOR_PLANNER,
    ROLE_OPS_MANAGER,
]


# ─── Shared bundles ───────────────────────────────────
TEST_USERS = {
    "facility_admin": build_user_headers(FACILITY_ADMIN_USER_ID, ROLE_FACILITY_ADMIN),
    "inbound_coordinator": build_user_headers(
        INBOUND_COORDINATOR_USER_ID, ROLE_INBOUND_COORDINATOR
    ),
    "sort_supervisor": build_user_headers(SORT_SUPERVISOR_USER_ID, ROLE_SORT_SUPERVISOR),
    "labor_planner": build_user_headers(LABOR_PLANNER_USER_ID, ROLE_LABOR_PLANNER),
    "labor_planner_2": build_user_headers(LABOR_PLANNER_2_USER_ID, ROLE_LABOR_PLANNER),
    "ops_manager": build_user_headers(OPS_MANAGER_USER_ID, ROLE_OPS_MANAGER),
    "ops_manager_2": build_user_headers(OPS_MANAGER_2_USER_ID, ROLE_OPS_MANAGER),
    "worker": build_user_headers(UNKNOWN_WORKER_USER_ID, ROLE_WORKER),
}

FACILITY_ADMIN_HEADERS = TEST_USERS["facility_admin"]
INBOUND_COORDINATOR_HEADERS = TEST_USERS["inbound_coordinator"]
SORT_SUPERVISOR_HEADERS = TEST_USERS["sort_supervisor"]
LABOR_PLANNER_HEADERS = TEST_USERS["labor_planner"]
OPS_MANAGER_HEADERS = TEST_USERS["ops_manager"]


# ─── Per-instance builders ────────────────────────────

def make_facility_admin_headers(user_id: str) -> dict:
    """Headers for a `FacilityAdmin` acting under a specific opaque identifier."""
    return build_user_headers(user_id, ROLE_FACILITY_ADMIN)


def make_inbound_coordinator_headers(user_id: str) -> dict:
    """Headers for an `InboundCoordinator` acting under a specific opaque identifier."""
    return build_user_headers(user_id, ROLE_INBOUND_COORDINATOR)


def make_sort_supervisor_headers(user_id: str) -> dict:
    """Headers for a `SortSupervisor` acting under a specific opaque identifier."""
    return build_user_headers(user_id, ROLE_SORT_SUPERVISOR)


def make_labor_planner_headers(user_id: str) -> dict:
    """Headers for a `LaborPlanner` acting under a specific opaque identifier.

    Use this when a test needs to control `submitted_by_user_id`.
    """
    return build_user_headers(user_id, ROLE_LABOR_PLANNER)


def make_ops_manager_headers(user_id: str) -> dict:
    """Headers for an `OpsManager` acting under a specific opaque identifier.

    Use this when a test needs the approver's identifier to equal (or to differ
    from) the plan's stored submitter.
    """
    return build_user_headers(user_id, ROLE_OPS_MANAGER)


def make_worker_headers(worker_id: str) -> dict:
    """Headers for the `Worker` role acting as the persisted worker `worker_id`.

    Mandatory for every check-in and check-out: the assignment's `worker_id`
    must equal `X-User-ID`.
    """
    return build_user_headers(worker_id, ROLE_WORKER)


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary identifier/role pair, including unknown roles."""
    return build_user_headers(user_id, role)
