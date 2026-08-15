"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. ProgramCoordinator is an opaque role: its X-User-ID is not
# compared to any entity id, so a shared constant is canonical.
# The GroupLeader shared constant is ONLY for tests that do not exercise
# ownership (e.g. registering a brand-new group, or 404/400 checks). Any
# ownership-gated call must use make_group_leader_headers(group["id"]).
TEST_USERS = {
    "coordinator_headers": build_user_headers("test-coordinator-1", "ProgramCoordinator"),
    "group_leader_headers": build_user_headers("test-group-leader-1", "GroupLeader"),
}


def make_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    """ProgramCoordinator headers (opaque identity; any id string is fine)."""
    return build_user_headers(user_id, "ProgramCoordinator")


def make_group_leader_headers(user_id: str) -> dict:
    """GroupLeader headers (entity_backed: AdopterGroup). Pass the actual
    AdopterGroup.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "GroupLeader")
