"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise
# membership ownership. ClubAdmin / RegisterClerk / ServiceDeskClerk are opaque
# identities not tied to any persisted entity.
TEST_USERS = {
    "club_admin_headers": build_user_headers("test-admin-1", "ClubAdmin"),
    "register_clerk_headers": build_user_headers("test-clerk-1", "RegisterClerk"),
    "service_desk_headers": build_user_headers("test-svc-1", "ServiceDeskClerk"),
    # Member is entity_backed:Membership — the shared constant is a fallback for
    # non-ownership tests only; ownership-gated calls must use make_member_headers.
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(membership_id: str) -> dict:
    """For Member (entity_backed:Membership). Pass the actual Membership.id as the
    acting principal whenever the call is ownership-gated."""
    return build_user_headers(membership_id, "Member")


def make_club_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ClubAdmin")


def make_register_clerk_headers(user_id: str = "test-clerk-1") -> dict:
    return build_user_headers(user_id, "RegisterClerk")


def make_service_desk_headers(user_id: str = "test-svc-1") -> dict:
    return build_user_headers(user_id, "ServiceDeskClerk")
