"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (CoalitionAdmin, AgencyNavigator,
# FinancialCoach): for these roles X-User-ID is not compared to any entity id
# (PRD §2.1). The entity-backed entries (InstitutionOfficer, Participant) are
# fallbacks for tests that do not exercise ownership; ownership-gated calls
# MUST use the per-instance builders below with the real entity id.
TEST_USERS = {
    "coalition_admin_headers": build_user_headers("test-admin-1", "CoalitionAdmin"),
    "agency_navigator_headers": build_user_headers("nav-1", "AgencyNavigator"),
    "financial_coach_headers": build_user_headers("coach-1", "FinancialCoach"),
    # entity_backed: fallbacks only for non-ownership checks.
    "institution_officer_headers": build_user_headers("test-officer-1", "InstitutionOfficer"),
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
}


def make_coalition_admin_headers(user_id: str) -> dict:
    """CoalitionAdmin is opaque, but segregation of duties compares the admin
    X-User-ID recorded at scoring against the finalizer's — use distinct ids."""
    return build_user_headers(user_id, "CoalitionAdmin")


def make_agency_navigator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AgencyNavigator")


def make_financial_coach_headers(coach_id: str) -> dict:
    """FinancialCoach X-User-ID is stored as pairing.coach_id; completion and
    follow-up calls compare the two, so pass the same coach_id used at create."""
    return build_user_headers(coach_id, "FinancialCoach")


def make_institution_officer_headers(institution_id: str) -> dict:
    """For InstitutionOfficer (entity_backed:PartnerInstitution). Pass the
    actual PartnerInstitution.id whenever the call is ownership-gated."""
    return build_user_headers(institution_id, "InstitutionOfficer")


def make_participant_headers(participant_id: str) -> dict:
    """For Participant (entity_backed:Participant). Pass the actual
    Participant.id whenever the call is ownership-gated."""
    return build_user_headers(participant_id, "Participant")
