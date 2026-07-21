"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles (Clerk, Manager), and for Member
# tests that do NOT exercise ownership (e.g. 401/403-by-role, 404 on missing).
TEST_USERS = {
    # opaque roles: the shared constant is the canonical form.
    "clerk_headers": build_user_headers("test-clerk-1", "Clerk"),
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    # entity_backed Member: shared constant is a fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated (act on own PreOrder/TradeIn/Rental)."""
    return build_user_headers(user_id, "Member")


def no_role_headers() -> dict:
    """Headers deliberately missing X-User-Role, for ERR_UNAUTHENTICATED tests."""
    return {"Content-Type": "application/json"}
