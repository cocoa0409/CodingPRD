"""Pre-built role headers for every role in the PRD (section 2.1).

FleetAdmin / ProjectManager / Dispatcher are opaque: X-User-ID is an operator
identifier never compared to any entity id. Mechanic is entity-backed: when
X-User-Role is Mechanic, X-User-ID MUST be the acting Mechanic entity's id,
because WorkOrder ownership checks compare work_order.mechanic_id to X-User-ID.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "fleet_admin_headers": build_user_headers("test-fleet-admin-1", "FleetAdmin"),
    "project_manager_headers": build_user_headers("test-project-manager-1", "ProjectManager"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    # Shared Mechanic constant is only safe for tests that do NOT exercise
    # work-order ownership (start/complete). Ownership-gated calls MUST use
    # make_mechanic_headers(mechanic["id"]) so X-User-ID equals the entity id.
    "mechanic_headers": build_user_headers("test-mechanic-1", "Mechanic"),
}


def make_fleet_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FleetAdmin")


def make_project_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProjectManager")


def make_dispatcher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_mechanic_headers(user_id: str) -> dict:
    """Mechanic is entity-backed: pass the actual Mechanic.id as user_id."""
    return build_user_headers(user_id, "Mechanic")
