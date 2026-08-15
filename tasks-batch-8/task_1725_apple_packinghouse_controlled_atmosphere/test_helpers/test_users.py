"""Pre-built role headers for every role in the PRD.

Admin, ReceivingClerk, StorageOperator, PackingSupervisor, and PoolManager are
opaque identities: X-User-ID is not tied to any persisted entity, so the shared
constants are their canonical form. Grower is entity-backed: X-User-ID must be
the acting Grower entity's id, so ownership-gated calls MUST use
make_grower_headers(grower_id) with the real entity id — never the shared
constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles; the grower entry is a fallback
# for tests that do not exercise ownership only.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "receiving_clerk_headers": build_user_headers("test-clerk-1", "ReceivingClerk"),
    "storage_operator_headers": build_user_headers("test-storage-1", "StorageOperator"),
    "packing_supervisor_headers": build_user_headers("test-supervisor-1", "PackingSupervisor"),
    "pool_manager_headers": build_user_headers("test-poolmgr-1", "PoolManager"),
    # entity_backed role: fallback for non-ownership tests only.
    "grower_headers": build_user_headers("test-grower-1", "Grower"),
}


def make_grower_headers(grower_id: str) -> dict:
    """For Grower (entity_backed:Grower). Pass the actual Grower.id whenever
    the call is ownership-gated (own record, blocks, lots, allocations,
    settlements)."""
    return build_user_headers(grower_id, "Grower")
