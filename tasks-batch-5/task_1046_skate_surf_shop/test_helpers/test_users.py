"""Pre-built role headers for every role in the PRD (§2.1).

ShopManager and Associate are opaque operator roles: their X-User-ID is not tied
to any persisted entity, so the shared constants are the canonical form.

Instructor and Member are entity-backed: their X-User-ID must equal the acting
Instructor.id / Member.id for ownership-gated calls. Use the per-instance builders
`make_instructor_headers(id)` / `make_member_headers(id)` for those.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — canonical shared constants.
    "shop_manager_headers": build_user_headers("test-shop-manager-1", "ShopManager"),
    "associate_headers": build_user_headers("test-associate-1", "Associate"),
    # Entity-backed roles — shared fallback for non-ownership tests only.
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}

# No-auth headers for authentication tests.
NO_AUTH_HEADERS: dict = {}


def make_instructor_headers(user_id: str) -> dict:
    """For Instructor (entity_backed:Instructor). Pass the actual Instructor.id
    whenever the call is ownership-gated (confirm/complete/cancel own lesson)."""
    return build_user_headers(user_id, "Instructor")


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id whenever the
    call is ownership-gated (own special orders / event registrations)."""
    return build_user_headers(user_id, "Member")
