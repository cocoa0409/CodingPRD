"""Pre-built role headers for every role named in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers.  Safe for the four opaque roles and for any test
# whose success does not depend on the caller owning the subject resource.
COORD_ADMIN = "coord-admin-0"
COORD_REVIEWER = "coord-review-1"
COORD_ISSUER = "coord-issue-2"
COORD_THIRD = "coord-issue-3"
LOGISTICS_USER = "log-user-1"
EMERGENCY_USER = "em-user-1"
AUDITOR_USER = "aud-user-1"

TEST_USERS = {
    "coordinator_headers": build_user_headers(COORD_ADMIN, "ProgramCoordinator"),
    "reviewer_coordinator_headers": build_user_headers(COORD_REVIEWER, "ProgramCoordinator"),
    "issuer_coordinator_headers": build_user_headers(COORD_ISSUER, "ProgramCoordinator"),
    "third_coordinator_headers": build_user_headers(COORD_THIRD, "ProgramCoordinator"),
    "logistics_headers": build_user_headers(LOGISTICS_USER, "LogisticsOfficer"),
    "emergency_headers": build_user_headers(EMERGENCY_USER, "EmergencyManager"),
    "auditor_headers": build_user_headers(AUDITOR_USER, "Auditor"),
    # Fallbacks for the three entity-backed roles.  Only ever appropriate for
    # tests that do not exercise an ownership check (for example a 404 probe).
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    "evaluator_headers": build_user_headers("test-evaluator-1", "SkillsEvaluator"),
    "trainee_headers": build_user_headers("test-trainee-1", "Trainee"),
}


def make_coordinator_headers(user_id: str) -> dict:
    """ProgramCoordinator acting under a specific opaque operator identifier."""
    return build_user_headers(user_id, "ProgramCoordinator")


def make_instructor_headers(instructor_id: str) -> dict:
    """Instructor role: pass the acting Instructor row's id as X-User-ID."""
    return build_user_headers(instructor_id, "Instructor")


def make_evaluator_headers(instructor_id: str) -> dict:
    """SkillsEvaluator role: X-User-ID is the acting Instructor row's id."""
    return build_user_headers(instructor_id, "SkillsEvaluator")


def make_trainee_headers(trainee_id: str) -> dict:
    """Trainee role: pass the acting Trainee row's id as X-User-ID."""
    return build_user_headers(trainee_id, "Trainee")


def make_logistics_headers(user_id: str = LOGISTICS_USER) -> dict:
    return build_user_headers(user_id, "LogisticsOfficer")


def make_emergency_headers(user_id: str = EMERGENCY_USER) -> dict:
    return build_user_headers(user_id, "EmergencyManager")


def make_auditor_headers(user_id: str = AUDITOR_USER) -> dict:
    return build_user_headers(user_id, "Auditor")
