"""Pre-built role headers for every role in the PRD (PRD §2.1).

Tenant is an entity-backed role: X-User-ID must equal the acting Tenancy's id.
Use make_tenant_headers(tenancy_id) for any ownership-gated tenant call;
TEST_USERS["tenant_headers"] is only a fallback for non-ownership contexts.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "manager_admin_headers": build_user_headers("test-admin-1", "ManagerAdmin"),
    "property_manager_headers": build_user_headers("test-pm-1", "PropertyManager"),
    "inspector_headers": build_user_headers("insp-1", "Inspector"),
    # Fallback only — ownership-gated calls must use make_tenant_headers(tenancy_id).
    "tenant_headers": build_user_headers("test-tenant-1", "Tenant"),
}


def make_manager_admin_headers(user_id: str = "test-admin-1") -> dict:
    """ManagerAdmin is an opaque role; any identifier is acceptable."""
    return build_user_headers(user_id, "ManagerAdmin")


def make_property_manager_headers(user_id: str = "test-pm-1") -> dict:
    """PropertyManager is an opaque role; any identifier is acceptable."""
    return build_user_headers(user_id, "PropertyManager")


def make_inspector_headers(user_id: str = "insp-1") -> dict:
    """Inspector is an opaque role; pass the inspector id for readability."""
    return build_user_headers(user_id, "Inspector")


def make_tenant_headers(tenancy_id: str) -> dict:
    """Tenant is entity-backed by Tenancy: X-User-ID MUST equal the tenancy id
    whenever the call is ownership-gated (disputes, close_agreed, escalate)."""
    return build_user_headers(tenancy_id, "Tenant")
