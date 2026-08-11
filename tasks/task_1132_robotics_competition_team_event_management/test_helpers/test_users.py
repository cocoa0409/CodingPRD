"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (TeamLead, Inspector, LeadInspector, HeadReferee,
Scorekeeper, Judge) MUST use the per-instance builders with the acting
Person's id whenever the call is ownership- or segregation-gated. The
shared constants are fallbacks for tests that do not exercise ownership
(role-rejection probes, 404 probes, opaque-role calls).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership tests.
TEST_USERS = {
    "event_director_headers": build_user_headers("test-event-director-1", "EventDirector"),
    "registration_officer_headers": build_user_headers("test-registration-officer-1", "RegistrationOfficer"),
    "screening_officer_headers": build_user_headers("test-screening-officer-1", "ScreeningOfficer"),
    "procurement_officer_headers": build_user_headers("test-procurement-officer-1", "ProcurementOfficer"),
    "queue_manager_headers": build_user_headers("test-queue-manager-1", "QueueManager"),
    "field_reset_crew_headers": build_user_headers("test-field-reset-crew-1", "FieldResetCrew"),
    "judge_advisor_headers": build_user_headers("test-judge-advisor-1", "JudgeAdvisor"),
    "travel_officer_headers": build_user_headers("test-travel-officer-1", "TravelOfficer"),
    # Entity-backed roles — fallback only for tests that never pass an
    # ownership/segregation check (e.g. RBAC rejection probes).
    "team_lead_headers": build_user_headers("test-team-lead-1", "TeamLead"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "lead_inspector_headers": build_user_headers("test-lead-inspector-1", "LeadInspector"),
    "head_referee_headers": build_user_headers("test-head-referee-1", "HeadReferee"),
    "scorekeeper_headers": build_user_headers("test-scorekeeper-1", "Scorekeeper"),
    "judge_headers": build_user_headers("test-judge-1", "Judge"),
}


# Per-instance builders — required for entity-backed roles on any call
# whose behavior depends on the caller's Person identity.
def make_team_lead_headers(person_id: str) -> dict:
    """TeamLead is entity-backed by Person; pass the acting Person.id."""
    return build_user_headers(person_id, "TeamLead")


def make_inspector_headers(person_id: str) -> dict:
    """Inspector is entity-backed by Person; pass the acting Person.id."""
    return build_user_headers(person_id, "Inspector")


def make_lead_inspector_headers(person_id: str) -> dict:
    """LeadInspector is entity-backed by Person; pass the acting Person.id."""
    return build_user_headers(person_id, "LeadInspector")


def make_head_referee_headers(person_id: str) -> dict:
    """HeadReferee is entity-backed by Person; pass the acting Person.id."""
    return build_user_headers(person_id, "HeadReferee")


def make_scorekeeper_headers(person_id: str) -> dict:
    """Scorekeeper is entity-backed by Person; pass the acting Person.id."""
    return build_user_headers(person_id, "Scorekeeper")


def make_judge_headers(person_id: str) -> dict:
    """Judge is entity-backed by Person; pass the acting Person.id."""
    return build_user_headers(person_id, "Judge")
