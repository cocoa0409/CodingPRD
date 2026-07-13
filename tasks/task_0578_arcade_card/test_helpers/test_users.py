"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   Cashier / Attendant / Coordinator / Manager identify by an opaque operator id
#   that the server never compares to any entity id, so the shared constant is the
#   canonical form for those roles.
#   The Member shared constant is a fallback for tests that do NOT exercise ownership
#   (e.g. reads); ownership-gated Member calls MUST use make_member_headers(member_id).
TEST_USERS = {
    "member_headers": build_user_headers("test-member-1", "Member"),
    "cashier_headers": build_user_headers("op-cashier-1", "Cashier"),
    "attendant_headers": build_user_headers("op-attendant-1", "Attendant"),
    "coordinator_headers": build_user_headers("op-coordinator-1", "Coordinator"),
    "manager_headers": build_user_headers("op-manager-1", "Manager"),
}


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id whenever
    the call is ownership-gated (playing / redeeming on the member's own card)."""
    return build_user_headers(user_id, "Member")
