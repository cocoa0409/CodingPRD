"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (schema failures, 404s on missing resources, role-deny checks).
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "coordinator_headers": build_user_headers("test-coordinator-1",
                                              "ProgramCoordinator"),
    "coordinator_a_headers": build_user_headers("coord-a",
                                                "ProgramCoordinator"),
    "coordinator_b_headers": build_user_headers("coord-b",
                                                "ProgramCoordinator"),
    # entity_backed roles: shared constants are a fallback for
    # non-ownership tests only; ownership-gated calls must use the
    # per-instance builders below with the entity's real id.
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
    "specialist_headers": build_user_headers("test-specialist-1", "Specialist"),
}


def make_volunteer_headers(user_id: str) -> dict:
    """For Volunteer (entity-backed by Volunteer). Pass the actual
    Volunteer.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Volunteer")


def make_specialist_headers(user_id: str) -> dict:
    """For Specialist (entity-backed by Specialist). Pass the actual
    Specialist.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Specialist")


def make_coordinator_headers(user_id: str) -> dict:
    """For ProgramCoordinator (opaque identity). Used when a test needs to
    distinguish two coordinator operators (e.g., segregation of duties)."""
    return build_user_headers(user_id, "ProgramCoordinator")
