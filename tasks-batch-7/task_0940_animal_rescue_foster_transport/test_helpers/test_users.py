"""Pre-built role headers for every role named in the PRD.

Seven roles are opaque identities whose X-User-ID is an operator identifier that
never has to resolve to a row: PlatformAdmin, IntakeOfficer, FosterCoordinator,
AdoptionCounselor, TransportDispatcher, Veterinarian and FinanceOfficer.

Four roles are entity-backed and their X-User-ID must resolve to a real row:
Driver, FosterParent and Adopter resolve to a Person; PartnerRescue resolves to
an Organization. Ownership-gated calls MUST use the per-instance builders below
with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# --------------------------------------------------------------------------
# Shared constants — safe for the opaque roles, and for entity-backed roles only
# in tests that never reach an ownership or identity-resolution check.
# --------------------------------------------------------------------------
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "intake_officer_headers": build_user_headers("intake-1", "IntakeOfficer"),
    "foster_coordinator_headers": build_user_headers("coord-1", "FosterCoordinator"),
    "adoption_counselor_headers": build_user_headers("counselor-1", "AdoptionCounselor"),
    "adoption_counselor_2_headers": build_user_headers("counselor-2", "AdoptionCounselor"),
    "adoption_counselor_3_headers": build_user_headers("counselor-3", "AdoptionCounselor"),
    "transport_dispatcher_headers": build_user_headers("dispatch-1", "TransportDispatcher"),
    "veterinarian_headers": build_user_headers("vet-1", "Veterinarian"),
    "finance_officer_headers": build_user_headers("finance-1", "FinanceOfficer"),
}

# Distinct operator identifiers used by the segregation-of-duties rule.
COUNSELOR_ONE = "counselor-1"
COUNSELOR_TWO = "counselor-2"
COUNSELOR_THREE = "counselor-3"


# --------------------------------------------------------------------------
# Per-instance builders — mandatory for every entity-backed role.
# --------------------------------------------------------------------------
def make_driver_headers(person_id: str) -> dict:
    """Driver acts as a Person; pass the driver Person id."""
    return build_user_headers(person_id, "Driver")


def make_foster_parent_headers(person_id: str) -> dict:
    """FosterParent acts as a Person; pass the foster parent Person id."""
    return build_user_headers(person_id, "FosterParent")


def make_adopter_headers(person_id: str) -> dict:
    """Adopter acts as a Person; pass the applicant/adopter Person id."""
    return build_user_headers(person_id, "Adopter")


def make_partner_rescue_headers(organization_id: str) -> dict:
    """PartnerRescue acts as an Organization; pass the partner Organization id."""
    return build_user_headers(organization_id, "PartnerRescue")


def make_counselor_headers(user_id: str) -> dict:
    """AdoptionCounselor with an explicit operator id (segregation of duties)."""
    return build_user_headers(user_id, "AdoptionCounselor")
