"""Pre-built role headers for every role in the PRD (§2.1).

Landlord, Tenant, and HearingOfficer are entity-backed: their X-User-ID must be
the id of a persisted actor for ownership checks. Use the make_* builders with a
real entity id whenever the call is ownership-gated.

RentBoardClerk and ComplianceOfficer are opaque operators: X-User-ID is a free
operator string that is never compared to an entity id (except the four-eyes
comparison between two ComplianceOfficer ids).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that don't exercise
# ownership. Entity-backed shared constants are fallbacks for non-ownership tests
# (e.g. 404-on-missing-resource, 400-on-bad-payload) only.
TEST_USERS = {
    "landlord_headers": build_user_headers("test-landlord-1", "Landlord"),
    "tenant_headers": build_user_headers("test-tenant-1", "Tenant"),
    "hearing_officer_headers": build_user_headers("test-officer-1", "HearingOfficer"),
    "clerk_headers": build_user_headers("test-clerk-1", "RentBoardClerk"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
}


# Per-instance builders — required for every entity-backed role.
def make_landlord_headers(user_id: str) -> dict:
    """For Landlord (entity_backed:Landlord). Pass the actual Landlord.id."""
    return build_user_headers(user_id, "Landlord")


def make_tenant_headers(user_id: str) -> dict:
    """For Tenant (entity_backed:Tenant). Pass the actual Tenant.id."""
    return build_user_headers(user_id, "Tenant")


def make_hearing_officer_headers(user_id: str) -> dict:
    """For HearingOfficer (entity_backed:HearingOfficer). Pass the actual HearingOfficer.id."""
    return build_user_headers(user_id, "HearingOfficer")


def make_clerk_headers(user_id: str = "test-clerk-1") -> dict:
    """For RentBoardClerk (opaque operator id)."""
    return build_user_headers(user_id, "RentBoardClerk")


def make_compliance_officer_headers(user_id: str) -> dict:
    """For ComplianceOfficer (opaque operator id). The four-eyes rule compares
    two ComplianceOfficer X-User-ID values, so tests must control this string."""
    return build_user_headers(user_id, "ComplianceOfficer")
