"""Pre-built role headers for every role in the PRD (Section 2.1).

There are exactly five roles: Vendor, PermitOfficer, HealthInspector,
EnforcementOfficer, Resident. Only Vendor is entity-backed: X-User-ID for a
Vendor must equal the acting Vendor's id, so ownership-gated calls use
make_vendor_headers(vendor_id). The other four roles are opaque operator
identifiers not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Stable opaque officer identifiers (used for four-eyes segregation).
OFFICER_ISSUER_ID = "off-1"
OFFICER_ADJUDICATOR_ID = "off-2"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "permit_officer_headers": build_user_headers("po-1", "PermitOfficer"),
    "health_inspector_headers": build_user_headers("hi-1", "HealthInspector"),
    "enforcement_officer_headers": build_user_headers(OFFICER_ISSUER_ID, "EnforcementOfficer"),
    "enforcement_officer_2_headers": build_user_headers(OFFICER_ADJUDICATOR_ID, "EnforcementOfficer"),
    "resident_headers": build_user_headers("res-1", "Resident"),
    # Vendor is entity_backed: this shared constant is a fallback for tests that
    # do NOT exercise ownership (e.g. 401/404 checks). Ownership-gated calls MUST
    # use make_vendor_headers(vendor["id"]).
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
}


def make_vendor_headers(vendor_id: str) -> dict:
    """Headers for a Vendor (entity_backed:Vendor). Pass the real Vendor.id as
    X-User-ID whenever the call is ownership-gated."""
    return build_user_headers(vendor_id, "Vendor")


def make_enforcement_headers(user_id: str) -> dict:
    """Headers for an EnforcementOfficer with an explicit opaque X-User-ID.
    Used to control four-eyes segregation (issuer vs adjudicator)."""
    return build_user_headers(user_id, "EnforcementOfficer")


def make_resident_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Resident")
