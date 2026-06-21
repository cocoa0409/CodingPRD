"""Pre-built role headers for every role in the PRD (PRD §2.1).

`Tenant` is the only entity-backed role (PRD §2.1): when `X-User-Role` is
`Tenant`, `X-User-ID` must equal an existing `Tenant.id`. For any
ownership-gated tenant call, callers MUST use `make_tenant_headers(tenant_id)`
with a real Tenant.id — the shared `TEST_USERS["tenant_headers"]` constant
carries a fake user-id string that never equals any real Tenant's UUID and
would therefore be rejected on ownership checks.

The other two roles (`HarborMaster`, `MarinaStaff`) are opaque (PRD §2.1):
the shared constants are the canonical form for those.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "harbor_master_headers": build_user_headers("test-harbor-master-1", "HarborMaster"),
    "marina_staff_headers": build_user_headers("test-marina-staff-1", "MarinaStaff"),
    # Entity-backed role — shared constant is a fallback for non-ownership
    # negative paths (401/404 etc.). Ownership-gated calls must use
    # make_tenant_headers(tenant["id"]).
    "tenant_headers": build_user_headers("test-tenant-1", "Tenant"),
}


def make_tenant_headers(tenant_id: str) -> dict:
    """Headers for the Tenant role bound to a specific Tenant.id (PRD §2.1)."""
    return build_user_headers(tenant_id, "Tenant")


def make_harbor_master_headers(user_id: str = "test-harbor-master-1") -> dict:
    return build_user_headers(user_id, "HarborMaster")


def make_marina_staff_headers(user_id: str = "test-marina-staff-1") -> dict:
    return build_user_headers(user_id, "MarinaStaff")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
