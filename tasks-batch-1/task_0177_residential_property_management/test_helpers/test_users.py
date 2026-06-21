"""Pre-built role headers for every role in the PRD (§2.1).

PropertyManager and ComplianceOfficer are opaque operator roles: X-User-ID is an
opaque identifier the server never matches against any entity id, so the shared
constants below are the canonical form for them.

Owner, Tenant, and Applicant are entity_backed: X-User-ID must equal the acting
entity's id for ownership-gated reads. The shared constants are fallbacks for
non-ownership tests (e.g. 401/403/404 paths); ownership-gated calls must use the
per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque operator roles — canonical form.
    "property_manager_headers": build_user_headers("test-pm-1", "PropertyManager"),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-1", "ComplianceOfficer"
    ),
    # entity_backed roles — shared fallback for non-ownership tests only.
    "owner_headers": build_user_headers("test-owner-1", "Owner"),
    "tenant_headers": build_user_headers("test-tenant-1", "Tenant"),
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}


def make_property_manager_headers(user_id: str = "test-pm-1") -> dict:
    """PropertyManager (opaque). user_id is never matched to an entity."""
    return build_user_headers(user_id, "PropertyManager")


def make_compliance_officer_headers(user_id: str = "test-compliance-1") -> dict:
    """ComplianceOfficer (opaque). user_id is never matched to an entity."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_owner_headers(user_id: str) -> dict:
    """Owner (entity_backed:Owner). Pass the actual Owner.id for ownership-gated reads."""
    return build_user_headers(user_id, "Owner")


def make_tenant_headers(user_id: str) -> dict:
    """Tenant (entity_backed:Tenant). Pass the actual Tenant.id for ownership-gated reads."""
    return build_user_headers(user_id, "Tenant")


def make_applicant_headers(user_id: str) -> dict:
    """Applicant (entity_backed:Applicant). Pass the actual Applicant.id for own-record reads."""
    return build_user_headers(user_id, "Applicant")
