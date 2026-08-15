"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for opaque roles, and fallbacks for non-ownership tests.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "ClinicalCoordinator"),
    # entity_backed fallbacks — only for tests that do NOT exercise ownership.
    "facilitator_headers": build_user_headers("test-facilitator-1", "Facilitator"),
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
}


def make_facilitator_headers(user_id: str) -> dict:
    """Facilitator is entity_backed: pass the actual Facilitator.id whenever the
    call is ownership-gated (own profile, complete/void on staffed sessions)."""
    return build_user_headers(user_id, "Facilitator")


def make_participant_headers(user_id: str) -> dict:
    """Participant is entity_backed: pass the actual Participant.id whenever the
    call is ownership-gated (own agreements, enrollments, check-ins, surveys)."""
    return build_user_headers(user_id, "Participant")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """ProgramAdmin is opaque; the id is not tied to any persisted entity."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    """ClinicalCoordinator is opaque; the id is not tied to any persisted entity."""
    return build_user_headers(user_id, "ClinicalCoordinator")
