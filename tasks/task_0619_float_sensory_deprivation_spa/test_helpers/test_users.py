"""Pre-built role headers for every role in the PRD (§2.1).

Three roles: Member (entity_backed — X-User-ID is the acting Member entity's id),
FrontDesk (opaque operator id), Admin (opaque operator id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (FrontDesk/Admin) and for Member tests that
# do NOT exercise ownership (e.g. 403-on-wrong-role, 404-on-missing-resource).
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "frontdesk_headers": build_user_headers("test-frontdesk-1", "FrontDesk"),
    # entity_backed Member: shared constant is a fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (own booking / membership / orientation)."""
    return build_user_headers(user_id, "Member")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "Admin")


def make_frontdesk_headers(user_id: str = "test-frontdesk-1") -> dict:
    return build_user_headers(user_id, "FrontDesk")
