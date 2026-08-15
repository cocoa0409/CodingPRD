"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles (AirportAdmin, ConcessionAnalyst,
# Auditor), whose X-User-ID participates in no ownership comparison (PRD §2.1).
# The Tenant shared constant is a fallback for non-ownership tests only.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "AirportAdmin"),
    "analyst_headers": build_user_headers("test-analyst-1", "ConcessionAnalyst"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # entity_backed role: fallback for non-ownership tests only.
    "tenant_headers": build_user_headers("test-tenant-1", "Tenant"),
}


def make_tenant_headers(user_id: str) -> dict:
    """For Tenant (identity is the Tenant record's id, PRD §2.1). Pass the actual
    Tenant.id as user_id whenever the call is ownership-gated (tenant-scoped writes
    compare the owning lease's tenant_id against X-User-ID)."""
    return build_user_headers(user_id, "Tenant")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AirportAdmin")


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ConcessionAnalyst")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")
