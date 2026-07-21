"""Pre-built role headers for every role in the PRD (§2.1).

Two entity-backed roles (Tenant, Landlord) carry an X-User-ID that is a real
persisted entity id and drives ownership checks — use the per-instance builders
with the actual entity id whenever a call is ownership-gated. The other three
roles are opaque operators whose id is never matched against an entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Fixed opaque-operator ids used across the suite.
ANALYST_1 = "analyst-1"
ANALYST_2 = "analyst-2"
OFFICER_1 = "officer-1"
OFFICER_2 = "officer-2"
ADMIN_1 = "admin-1"


TEST_USERS = {
    # Opaque operators — the shared constant IS the canonical form for these.
    "analyst_headers": build_user_headers(ANALYST_1, "ComplianceAnalyst"),
    "analyst2_headers": build_user_headers(ANALYST_2, "ComplianceAnalyst"),
    "officer_headers": build_user_headers(OFFICER_1, "ComplianceOfficer"),
    "officer2_headers": build_user_headers(OFFICER_2, "ComplianceOfficer"),
    "admin_headers": build_user_headers(ADMIN_1, "PlatformAdmin"),
    # Entity-backed roles — shared constants are a fallback for NON-ownership
    # tests only (e.g. 401/403/404 probes). Ownership-gated calls MUST use the
    # per-instance builders below with the real entity id.
    "tenant_headers": build_user_headers("test-tenant-1", "Tenant"),
    "landlord_headers": build_user_headers("test-landlord-1", "Landlord"),
}


# Per-instance builders — required for every entity-backed role.
def make_tenant_headers(tenant_id: str) -> dict:
    """For Tenant (entity_backed:Tenant). Pass the actual Tenant.id whenever the
    call is ownership-gated (enrollments, leases, disputes, invoices, ...)."""
    return build_user_headers(tenant_id, "Tenant")


def make_landlord_headers(landlord_id: str) -> dict:
    """For Landlord (entity_backed:Landlord). Pass the actual Landlord.id whenever
    the call is ownership-gated (lease verification, rent-payment recording)."""
    return build_user_headers(landlord_id, "Landlord")


def make_analyst_headers(user_id: str) -> dict:
    """For ComplianceAnalyst (opaque). Lets a test pin the operator id (SoD)."""
    return build_user_headers(user_id, "ComplianceAnalyst")


def make_officer_headers(user_id: str) -> dict:
    """For ComplianceOfficer (opaque). Lets a test pin the operator id (SoD)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
