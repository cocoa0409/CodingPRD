"""Pre-built role headers for every role in the PRD (§2.1).

Member is entity_backed:User — ownership checks compare X-User-ID against the
resource's owner FK, so ownership-gated calls MUST use make_member_headers(user_id)
with the actual User.id. Guest, Moderator, and Admin are opaque operator roles whose
X-User-ID is never compared to any entity id, so shared constants are correct for them.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles, plus Member fallback for non-ownership tests only.
TEST_USERS = {
    "guest_headers": build_user_headers("guest-visitor-1", "Guest"),
    "member_headers": build_user_headers("test-member-1", "Member"),
    "moderator_headers": build_user_headers("test-moderator-1", "Moderator"),
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
}

# Headers that carry no auth at all — for the unauthenticated (401) case.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:User). Pass the actual User.id as user_id whenever
    the call is ownership-gated (petition author, signer, purchaser, donor, etc.)."""
    return build_user_headers(user_id, "Member")


def make_guest_headers(user_id: str = "guest-visitor-1") -> dict:
    return build_user_headers(user_id, "Guest")
