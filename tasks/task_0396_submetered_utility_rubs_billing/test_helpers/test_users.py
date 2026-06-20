"""Pre-built role headers for every role in the PRD.

All four roles carry an opaque X-User-ID. For PropertyManager, MeterTech, and
Auditor the id is a free operator identifier the server never compares to an
entity. For Tenant the id is still opaque but carries ownership meaning: it is
matched against a Lease.tenant_user_id. Ownership-gated tenant calls therefore
MUST use make_tenant_headers(tenant_user_id) with the SAME string passed as the
lease's tenant_user_id at creation time.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque operator roles and for non-ownership
# tenant tests (e.g. missing-resource / wrong-role checks).
TEST_USERS = {
    "property_manager_headers": build_user_headers("test-pm-1", "PropertyManager"),
    "meter_tech_headers": build_user_headers("test-tech-1", "MeterTech"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # A generic tenant header; only valid for ownership-independent tenant tests.
    "tenant_headers": build_user_headers("test-tenant-1", "Tenant"),
}


def make_tenant_headers(tenant_user_id: str) -> dict:
    """For the Tenant role. Pass the SAME opaque string used as a Lease's
    tenant_user_id whenever the call is ownership-gated (payments, disputes,
    reopen, give-notice on own lease)."""
    return build_user_headers(tenant_user_id, "Tenant")


def make_pm_headers(user_id: str = "test-pm-1") -> dict:
    return build_user_headers(user_id, "PropertyManager")


def make_meter_tech_headers(user_id: str = "test-tech-1") -> dict:
    return build_user_headers(user_id, "MeterTech")
