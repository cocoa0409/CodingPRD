"""Pre-built role headers for every role in the PRD.

PRD §2.1: PlatformAdmin, StateApiarist, ContractCoordinator carry an opaque
X-User-ID. ApiaryManager is entity_backed:Apiary — its X-User-ID must equal the
id of the acting Apiary for ownership-gated mutations, so a per-instance builder
is mandatory.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# Apiary ownership (e.g. 400/404 paths, role-denial checks).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "state_apiarist_headers": build_user_headers("test-apiarist-1", "StateApiarist"),
    "contract_coordinator_headers": build_user_headers(
        "test-coordinator-1", "ContractCoordinator"),
    # ApiaryManager: shared constant is a non-ownership fallback only.
    "apiary_manager_headers": build_user_headers("test-manager-1", "ApiaryManager"),
}


def make_apiary_manager_headers(apiary_id: str) -> dict:
    """For ApiaryManager (entity_backed:Apiary). Pass the actual Apiary.id as the
    X-User-ID whenever the call is ownership-gated (hives, inspections, treatments,
    harvests, honey lots, feedings, requeen schedules owned by that apiary)."""
    return build_user_headers(apiary_id, "ApiaryManager")
