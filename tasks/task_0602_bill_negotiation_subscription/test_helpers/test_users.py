"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlatformAdmin) and for tests that
# do not exercise ownership (e.g., 400/404/401/403-role checks).
TEST_USERS = {
    # entity_backed:Member — shared constant is a fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
    # entity_backed:ConciergeAgentProfile — shared constant fallback for non-ownership tests.
    "agent_headers": build_user_headers("test-agent-1", "ConciergeAgent"),
    # opaque role: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_member_headers(member_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id whenever
    the call is ownership-gated."""
    return build_user_headers(member_id, "Member")


def make_agent_headers(agent_id: str) -> dict:
    """For ConciergeAgent (entity_backed:ConciergeAgentProfile). Pass the actual
    ConciergeAgentProfile.id as user_id."""
    return build_user_headers(agent_id, "ConciergeAgent")


def make_admin_headers(admin_id: str = "test-admin-1") -> dict:
    """For PlatformAdmin (opaque). Operator id is not tied to any entity."""
    return build_user_headers(admin_id, "PlatformAdmin")
