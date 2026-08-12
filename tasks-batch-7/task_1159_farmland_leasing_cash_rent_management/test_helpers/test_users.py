"""Pre-built role headers for every role in the PRD (§2.1).

`FarmManager` and `System` are opaque identities: X-User-ID is recorded but
never compared to an entity id, so shared constants are safe for them.

`Landlord` and `Tenant` are entity-backed: X-User-ID must be the acting
entity's `id` whenever the call is ownership-gated. Use the per-instance
builders below for those calls; the shared constants exist only for tests that
do not exercise ownership (e.g., role-denial checks on master-data creation).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque FarmManager identities (safe as shared constants).
    "farm_manager_headers": build_user_headers("mgr-default", "FarmManager"),
    "mgr_1_headers": build_user_headers("mgr-1", "FarmManager"),
    "mgr_2_headers": build_user_headers("mgr-2", "FarmManager"),
    "mgr_3_headers": build_user_headers("mgr-3", "FarmManager"),
    # Entity-backed fallbacks — NON-ownership tests only. Ownership-gated
    # calls MUST use make_landlord_headers(entity_id) / make_tenant_headers(entity_id).
    "landlord_headers": build_user_headers("test-landlord-1", "Landlord"),
    "tenant_headers": build_user_headers("test-tenant-1", "Tenant"),
}


def make_farm_manager_headers(user_id: str) -> dict:
    """Opaque manager identity (e.g. mgr-1 / mgr-2 for segregation-of-duties)."""
    return build_user_headers(user_id, "FarmManager")


def make_landlord_headers(user_id: str) -> dict:
    """Entity-backed landlord identity. Pass the Landlord.id for ownership-gated
    calls (award, improvement approve/reject, report acknowledge, notices)."""
    return build_user_headers(user_id, "Landlord")


def make_tenant_headers(user_id: str) -> dict:
    """Entity-backed tenant identity. Pass the Tenant.id for ownership-gated
    calls (bid create/revise/withdraw, expenses, evidence, notices)."""
    return build_user_headers(user_id, "Tenant")
