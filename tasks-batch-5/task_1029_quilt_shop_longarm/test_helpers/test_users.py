"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   Clerk and Manager are opaque roles (X-User-ID is an operator id not tied to any entity),
#   so the shared constant is their canonical form.
#   Member is entity_backed: the shared constant is a fallback for non-ownership tests only;
#   ownership-gated Member calls MUST use make_member_headers(member_id).
TEST_USERS = {
    "clerk_headers": build_user_headers("clerk-op-1", "Clerk"),
    "manager_headers": build_user_headers("manager-op-1", "Manager"),
    "member_headers": build_user_headers("member-fallback-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the acting Member.id as user_id
    whenever the call is ownership-gated (§2.1: ownership compares resource.member_id to
    X-User-ID)."""
    return build_user_headers(user_id, "Member")


def make_clerk_headers(user_id: str = "clerk-op-1") -> dict:
    return build_user_headers(user_id, "Clerk")


def make_manager_headers(user_id: str = "manager-op-1") -> dict:
    return build_user_headers(user_id, "Manager")
