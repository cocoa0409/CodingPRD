"""Pre-built role headers for every role in the PRD (§2.1).

Five caller roles carry an OPAQUE identity (PlatformAdmin, Underwriter,
ClaimsAdjuster, RecoveryAgent, ComplianceOfficer): their X-User-ID is a free
operator identifier the server never compares to an entity id, but it IS
recorded for later segregation-of-duties checks (guarantee.underwritten_by_user_id,
review.opened_by_user_id). The two entity-backed roles (Landlord, Applicant)
must carry the acting entity's own id as X-User-ID.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator ids used to drive segregation-of-duties scenarios.
UW1 = "uw1"          # underwriter of record
UW2 = "uw2"          # second underwriter (SoD-safe)
CA1 = "ca1"          # claims adjuster (distinct from UW1)
CO1 = "co1"          # compliance opener
CO2 = "co2"          # second compliance officer (SoD-safe resolver)
RA1 = "ra1"          # recovery agent
ADMIN1 = "admin1"    # platform admin

# Shared constants — safe for opaque roles and for tests that do not exercise
# entity ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers(ADMIN1, "PlatformAdmin"),
    "underwriter_headers": build_user_headers(UW1, "Underwriter"),
    "claims_adjuster_headers": build_user_headers(CA1, "ClaimsAdjuster"),
    "recovery_agent_headers": build_user_headers(RA1, "RecoveryAgent"),
    "compliance_officer_headers": build_user_headers(CO1, "ComplianceOfficer"),
    # Landlord/Applicant shared constants: fallback only for non-ownership tests
    # (e.g. 404/forbidden-role checks). Ownership-gated calls MUST use the
    # per-instance builders below with the real entity id.
    "landlord_headers": build_user_headers("landlord-fallback", "Landlord"),
    "applicant_headers": build_user_headers("applicant-fallback", "Applicant"),
}


# --- Per-instance builders for opaque roles that need a specific X-User-ID
#     (segregation-of-duties comparisons) ---
def make_underwriter_headers(user_id: str = UW1) -> dict:
    """Underwriter acting under a specific operator id (recorded as
    guarantee.underwritten_by_user_id on approve)."""
    return build_user_headers(user_id, "Underwriter")


def make_claims_adjuster_headers(user_id: str = CA1) -> dict:
    """ClaimsAdjuster acting under a specific operator id. Pass UW1 to force a
    segregation-of-duties clash on claim approve."""
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_compliance_officer_headers(user_id: str = CO1) -> dict:
    """ComplianceOfficer acting under a specific operator id (recorded as
    review.opened_by_user_id on open)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_platform_admin_headers(user_id: str = ADMIN1) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_recovery_agent_headers(user_id: str = RA1) -> dict:
    return build_user_headers(user_id, "RecoveryAgent")


# --- Per-instance builders for entity-backed roles (MANDATORY for ownership) ---
def make_landlord_headers(landlord_id: str) -> dict:
    """For a Landlord (entity_backed:Landlord). Pass the real Landlord.id so
    ownership checks (agreement sign, claim create/withdraw) succeed."""
    return build_user_headers(landlord_id, "Landlord")


def make_applicant_headers(applicant_id: str) -> dict:
    """For an Applicant (entity_backed:Applicant). Pass the real Applicant.id so
    the pay-fee ownership check (guarantee.applicant_id == X-User-ID) succeeds."""
    return build_user_headers(applicant_id, "Applicant")
