"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (ComplianceOfficer, UtilityAgent) and
# for tests that never exercise entity-backed ownership. Entity-backed roles
# (BuildingOwner -> Owner.id, TenantRep -> TenantUnit.id, DataVerifier ->
# Verifier.id) MUST use the per-instance builders below whenever the call is
# ownership-gated; the shared fallback's X-User-ID matches no real entity.
TEST_USERS = {
    "officer_headers": build_user_headers("officer-1", "ComplianceOfficer"),
    "officer2_headers": build_user_headers("officer-2", "ComplianceOfficer"),
    "utility_agent_headers": build_user_headers("utility-agent-1", "UtilityAgent"),
    # Fallbacks for non-ownership tests only.
    "owner_headers": build_user_headers("test-owner-fallback", "BuildingOwner"),
    "tenant_rep_headers": build_user_headers("test-tenant-fallback", "TenantRep"),
    "verifier_headers": build_user_headers("test-verifier-fallback", "DataVerifier"),
}


def make_owner_headers(owner_id: str) -> dict:
    """BuildingOwner is entity-backed by Owner: X-User-ID must be the Owner id."""
    return build_user_headers(owner_id, "BuildingOwner")


def make_tenant_rep_headers(tenant_unit_id: str) -> dict:
    """TenantRep is entity-backed by TenantUnit: X-User-ID must be the unit id."""
    return build_user_headers(tenant_unit_id, "TenantRep")


def make_verifier_headers(verifier_id: str) -> dict:
    """DataVerifier is entity-backed by Verifier: X-User-ID must be the Verifier id."""
    return build_user_headers(verifier_id, "DataVerifier")


def make_officer_headers(officer_id: str) -> dict:
    """ComplianceOfficer identity is opaque; the id is recorded on created cycles."""
    return build_user_headers(officer_id, "ComplianceOfficer")
