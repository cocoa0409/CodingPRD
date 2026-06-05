"""Pre-built role headers for every role in the PRD (§2.1).

FacilityManager and LienAdministrator are opaque operators: their X-User-ID is a
constant operator id never compared to any entity. Tenant is entity_backed:Tenant,
so ownership-gated calls MUST use make_tenant_headers(tenant_id) with the real id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — the shared constant is the canonical form.
    "facility_manager_headers": build_user_headers("op-fm-1", "FacilityManager"),
    "lien_administrator_headers": build_user_headers("op-lien-1", "LienAdministrator"),
    # Tenant fallback constant — safe ONLY for tests that do not exercise ownership
    # (e.g. 403 peer-isolation negatives, where the id must deliberately differ).
    "tenant_headers": build_user_headers("test-tenant-1", "Tenant"),
}


def make_tenant_headers(user_id: str) -> dict:
    """For Tenant (entity_backed:Tenant). Pass the acting Tenant.id as user_id so
    ownership checks (resource.tenant_id == X-User-ID) pass."""
    return build_user_headers(user_id, "Tenant")


def make_facility_manager_headers(user_id: str = "op-fm-1") -> dict:
    return build_user_headers(user_id, "FacilityManager")


def make_lien_administrator_headers(user_id: str = "op-lien-1") -> dict:
    return build_user_headers(user_id, "LienAdministrator")
