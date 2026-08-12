"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # entity_backed:Member — shared constant is a fallback for non-ownership tests only.
    # For ownership-gated calls, use make_member_headers(member["id"]).
    "member_headers": build_user_headers("test-member-1", "Member"),
    # opaque roles
    "membership_admin_headers": build_user_headers("test-membership-admin-1", "MembershipAdministrator"),
    "dues_admin_headers": build_user_headers("test-dues-admin-1", "DuesAdministrator"),
}


# Per-instance builders — required for entity_backed roles.
def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Member")


def make_membership_admin_headers(user_id: str = "test-membership-admin-1") -> dict:
    return build_user_headers(user_id, "MembershipAdministrator")


def make_dues_admin_headers(user_id: str = "test-dues-admin-1") -> dict:
    return build_user_headers(user_id, "DuesAdministrator")
