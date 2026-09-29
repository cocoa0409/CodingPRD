"""Pre-built role headers for every role in the PRD.

All five roles use an opaque identity model (PRD §2.1): X-User-ID is an operator
identifier, never an entity id. For `BuildingManager` and `ServiceContractor` the
server compares it against the governing contract's `building_manager_user_id` /
`contractor_user_id`, so every call on behalf of those two roles MUST be built
with the exact operator id recorded on the contract under test — use the
per-identity builders below, not the shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator identifiers used by the fixtures.
DEFAULT_ADMIN_USER_ID = "pa-1"
SECOND_ADMIN_USER_ID = "pa-2"
DEFAULT_MANAGER_USER_ID = "bm-1"
DEFAULT_CONTRACTOR_USER_ID = "sc-1"
DEFAULT_INSPECTOR_USER_ID = "si-1"
DEFAULT_DISPATCHER_USER_ID = "fd-1"

# Shared constants — safe for the roles that are never contract parties
# (ProgramAdministrator, StateInspector, FireDispatcher) and for any call whose
# outcome does not depend on the contract-party binding.
TEST_USERS = {
    "admin_headers": build_user_headers(DEFAULT_ADMIN_USER_ID, "ProgramAdministrator"),
    "second_admin_headers": build_user_headers(
        SECOND_ADMIN_USER_ID, "ProgramAdministrator"
    ),
    "inspector_headers": build_user_headers(DEFAULT_INSPECTOR_USER_ID, "StateInspector"),
    "dispatcher_headers": build_user_headers(
        DEFAULT_DISPATCHER_USER_ID, "FireDispatcher"
    ),
    "building_manager_headers": build_user_headers(
        DEFAULT_MANAGER_USER_ID, "BuildingManager"
    ),
    "contractor_headers": build_user_headers(
        DEFAULT_CONTRACTOR_USER_ID, "ServiceContractor"
    ),
}


def make_admin_headers(user_id: str = DEFAULT_ADMIN_USER_ID) -> dict:
    """Headers for a ProgramAdministrator acting under the given operator id."""
    return build_user_headers(user_id, "ProgramAdministrator")


def make_building_manager_headers(user_id: str) -> dict:
    """Headers for a BuildingManager.

    Pass the contract's `building_manager_user_id`; any other value is refused
    with ERR_NOT_CONTRACT_PARTY.
    """
    return build_user_headers(user_id, "BuildingManager")


def make_contractor_headers(user_id: str) -> dict:
    """Headers for a ServiceContractor.

    Pass the contract's `contractor_user_id`; any other value is refused with
    ERR_NOT_CONTRACT_PARTY.
    """
    return build_user_headers(user_id, "ServiceContractor")


def make_inspector_headers(user_id: str = DEFAULT_INSPECTOR_USER_ID) -> dict:
    """Headers for a StateInspector (never a contract party)."""
    return build_user_headers(user_id, "StateInspector")


def make_dispatcher_headers(user_id: str = DEFAULT_DISPATCHER_USER_ID) -> dict:
    """Headers for a FireDispatcher (never a contract party)."""
    return build_user_headers(user_id, "FireDispatcher")


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary user id / role pair."""
    return build_user_headers(user_id, role)


# The deliberate absence of both auth headers (PRD §2.1 → ERR_UNAUTHENTICATED).
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}
