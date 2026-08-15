"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# entity-backed ownership.
TEST_USERS = {
    # opaque roles: shared constants are canonical
    "coordinator_headers": build_user_headers("sc-1", "ShopCoordinator"),
    "coordinator_2_headers": build_user_headers("sc-2", "ShopCoordinator"),
    "coordinator_approver_headers": build_user_headers("sc-approver-1", "ShopCoordinator"),
    "coordinator_logger_headers": build_user_headers("sc-logger-1", "ShopCoordinator"),
    "director_headers": build_user_headers("pd-1", "ProgramDirector"),
    "director_2_headers": build_user_headers("pd-2", "ProgramDirector"),
    "director_9_headers": build_user_headers("pd-9", "ProgramDirector"),
    # entity_backed roles: fallback only for tests that do not exercise ownership
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}


# Per-instance builders — required for entity_backed roles. Pass the actual
# entity id as user_id whenever the call is ownership-gated.
def make_volunteer_headers(user_id: str) -> dict:
    """Volunteer role headers whose X-User-ID is the actual Volunteer.id."""
    return build_user_headers(user_id, "Volunteer")


def make_participant_headers(user_id: str) -> dict:
    """Participant role headers whose X-User-ID is the actual EarnABikeParticipant.id."""
    return build_user_headers(user_id, "Participant")


def make_member_headers(user_id: str) -> dict:
    """Member role headers whose X-User-ID is the actual ToolMembership.id."""
    return build_user_headers(user_id, "Member")


def make_coordinator_headers(user_id: str) -> dict:
    """Opaque ShopCoordinator identity (audit fields, segregation-of-duties pairs)."""
    return build_user_headers(user_id, "ShopCoordinator")


def make_director_headers(user_id: str) -> dict:
    """Opaque ProgramDirector identity (audit fields, segregation-of-duties pairs)."""
    return build_user_headers(user_id, "ProgramDirector")
