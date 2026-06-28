"""Pre-built role headers for every role in the PRD (PRD §2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   PlatformAdmin / ReviewAgent / FinanceAdmin are opaque operator identities
#   (PRD §2.1: X-User-ID is not tied to any persisted entity), so the shared
#   constant is the canonical form for those roles.
#   The Member shared constant is a fallback ONLY for tests that do not exercise
#   ownership (e.g., 401/403 negative checks). Ownership-gated Member calls MUST
#   use make_member_headers(member_id) below.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "review_agent_headers": build_user_headers("test-review-agent-1", "ReviewAgent"),
    "finance_admin_headers": build_user_headers("test-finance-admin-1", "FinanceAdmin"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated (PRD §2.1: when X-User-Role is
    Member, X-User-ID is the id of the acting Member row)."""
    return build_user_headers(user_id, "Member")
