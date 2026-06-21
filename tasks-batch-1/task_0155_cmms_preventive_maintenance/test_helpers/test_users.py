"""Pre-built role headers for every role in the PRD (§2.1).

Per PRD §2.1, Technician is entity-backed: X-User-ID is the id of the acting
Technician entity, and ownership checks on work-order execution actions compare
the work order's assigned_technician_id to X-User-ID. The other four roles
(MaintenanceManager, Planner, InventoryClerk, WarrantyAdmin) carry an opaque
operator id that is never compared to any entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# Technician ownership (e.g. RBAC denials, 404s, bad-payload 400s).
TEST_USERS = {
    "manager_headers": build_user_headers("op-manager-1", "MaintenanceManager"),
    "planner_headers": build_user_headers("op-planner-1", "Planner"),
    "technician_headers": build_user_headers("op-technician-1", "Technician"),
    "inventory_clerk_headers": build_user_headers("op-clerk-1", "InventoryClerk"),
    "warranty_admin_headers": build_user_headers("op-warranty-1", "WarrantyAdmin"),
    # An unrecognized role for ERR_UNAUTHENTICATED tests.
    "ghost_headers": build_user_headers("op-ghost-1", "Ghost"),
}


def make_technician_headers(technician_id: str) -> dict:
    """Headers for the Technician role (entity_backed:Technician).

    Pass the actual Technician.id as the user id whenever the call is an
    ownership-gated execution action (start / hold / resume / close), so the
    server's assigned_technician_id == X-User-ID check passes.
    """
    return build_user_headers(technician_id, "Technician")
