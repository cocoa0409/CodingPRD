"""Pre-built role headers for every role in the PRD (§2.1).

FlightCrew is entity-backed (X-User-ID is the acting CrewMember.id), so any
ownership-gated call must use make_flight_crew_headers(crew_member["id"]) with
the real entity id. The shared constant is only for calls that do not exercise
ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "medical_director_headers": build_user_headers("test-medical-director-1", "MedicalDirector"),
    # Fallback only for FlightCrew calls that are NOT ownership-gated.
    "flight_crew_headers": build_user_headers("test-flight-crew-1", "FlightCrew"),
    "billing_specialist_headers": build_user_headers("test-billing-specialist-1", "BillingSpecialist"),
    "qa_reviewer_headers": build_user_headers("test-qa-reviewer-1", "QaReviewer"),
}


def make_flight_crew_headers(crew_member_id: str) -> dict:
    """FlightCrew is entity-backed: pass the acting CrewMember's id whenever the
    call is ownership-gated (weather filing, PCR create/submit/amend, own-shift
    create/close, mission advance/abort/divert as that member)."""
    return build_user_headers(crew_member_id, "FlightCrew")


def make_qa_reviewer_headers(user_id: str) -> dict:
    """QaReviewer with a chosen opaque id (used to vary reviewer identity for
    the segregation-of-duties rule)."""
    return build_user_headers(user_id, "QaReviewer")
