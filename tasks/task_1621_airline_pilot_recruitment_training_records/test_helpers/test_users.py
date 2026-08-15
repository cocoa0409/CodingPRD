"""Pre-built role headers for every role in the PRD.

Recruiter, TrainingCoordinator, CrewScheduler, and SystemAdmin are opaque
identities: X-User-ID is not tied to any persisted entity. CheckAirman is
entity-backed by Instructor and Pilot is entity-backed by Applicant, so
ownership-gated calls MUST use the per-instance builders with the real
entity id; the shared constants are fallbacks for non-ownership tests only.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "recruiter_headers": build_user_headers("test-recruiter-1", "Recruiter"),
    "training_coordinator_headers": build_user_headers(
        "test-coordinator-1", "TrainingCoordinator"),
    "crew_scheduler_headers": build_user_headers("test-scheduler-1", "CrewScheduler"),
    "system_admin_headers": build_user_headers("test-admin-1", "SystemAdmin"),
    # entity_backed roles: shared constants are fallbacks for
    # non-ownership tests only.
    "check_airman_headers": build_user_headers("test-airman-1", "CheckAirman"),
    "pilot_headers": build_user_headers("test-pilot-1", "Pilot"),
}


def make_recruiter_headers(user_id: str = "test-recruiter-1") -> dict:
    return build_user_headers(user_id, "Recruiter")


def make_training_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    return build_user_headers(user_id, "TrainingCoordinator")


def make_crew_scheduler_headers(user_id: str = "test-scheduler-1") -> dict:
    return build_user_headers(user_id, "CrewScheduler")


def make_system_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_check_airman_headers(instructor_id: str) -> dict:
    """For CheckAirman (entity_backed:Instructor). Pass the acting
    Instructor.id whenever the call is identity-gated (e.g. recording a
    checkride outcome compares X-User-ID to the ride's check_airman_id)."""
    return build_user_headers(instructor_id, "CheckAirman")


def make_pilot_headers(applicant_id: str) -> dict:
    """For Pilot (entity_backed:Applicant). Pass the acting Applicant.id
    whenever the call is ownership-gated (own record read, own bids,
    own withdrawal)."""
    return build_user_headers(applicant_id, "Pilot")
