"""Pre-built role headers for every role in the PRD.

Six roles are entity-backed (X-User-ID must equal an existing PartyProfile.id);
CaseAdministrator is opaque. The shared constants are therefore safe ONLY for
CaseAdministrator. Every other role MUST be built per-instance with the actual
profile id via the make_*_headers builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: shared constant is the canonical form.
    "case_admin_headers": build_user_headers("test-case-admin-1", "CaseAdministrator"),
}


def make_coordinator_headers(user_id: str) -> dict:
    """TitleIXCoordinator (entity-backed): pass the coordinator PartyProfile.id."""
    return build_user_headers(user_id, "TitleIXCoordinator")


def make_investigator_headers(user_id: str) -> dict:
    """Investigator (entity-backed): pass the investigator PartyProfile.id."""
    return build_user_headers(user_id, "Investigator")


def make_decision_maker_headers(user_id: str) -> dict:
    """DecisionMaker (entity-backed): pass the decision-maker PartyProfile.id."""
    return build_user_headers(user_id, "DecisionMaker")


def make_appeal_officer_headers(user_id: str) -> dict:
    """AppealOfficer (entity-backed): pass the appeal officer PartyProfile.id."""
    return build_user_headers(user_id, "AppealOfficer")


def make_party_headers(user_id: str) -> dict:
    """Party (entity-backed): pass the complainant/respondent PartyProfile.id."""
    return build_user_headers(user_id, "Party")


def make_advisor_headers(user_id: str) -> dict:
    """Advisor (entity-backed): pass the advisor PartyProfile.id."""
    return build_user_headers(user_id, "Advisor")
