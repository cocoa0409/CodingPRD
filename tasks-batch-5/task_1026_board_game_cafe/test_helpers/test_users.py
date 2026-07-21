"""Pre-built role headers for every role in the PRD.

Manager and Staff carry opaque X-User-IDs not tied to any persisted entity, so
their shared constants are the canonical form for every call.

Member is entity-backed: its X-User-ID is the acting Membership's id. Ownership
checks compare a resource's membership_id to that id, so any ownership-gated
call (a member acting on its own reservation, registration, redemption, or
retail order) MUST use make_member_headers(membership["id"]) — never the shared
constant, which is a string that equals no real membership id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque operator roles, and for Member tests
# that do not exercise ownership.
TEST_USERS = {
    "manager_headers": build_user_headers("mgr-1", "Manager"),
    "staff_headers": build_user_headers("staff-1", "Staff"),
    # Fallback for non-ownership Member tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_manager_headers(user_id: str) -> dict:
    """Manager (opaque operator id)."""
    return build_user_headers(user_id, "Manager")


def make_staff_headers(user_id: str) -> dict:
    """Staff (opaque operator id)."""
    return build_user_headers(user_id, "Staff")


def make_member_headers(user_id: str) -> dict:
    """Member (entity_backed:Membership). Pass the acting Membership.id as user_id
    whenever the call is ownership-gated (own reservation/registration/redemption/
    retail order)."""
    return build_user_headers(user_id, "Member")


def make_anonymous_headers() -> dict:
    """Sentinel unknown role — exercises the ERR_UNAUTHENTICATED path (a role that
    is not one of Manager, Staff, Member)."""
    return build_user_headers("anon-1", "Anonymous")
