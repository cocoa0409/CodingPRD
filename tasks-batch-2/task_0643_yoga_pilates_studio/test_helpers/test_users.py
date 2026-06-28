"""Pre-built role headers for every role in the Yoga & Pilates Studio PRD §2.1.

Three roles exist:
  - StudioManager: identity is opaque (X-User-ID not tied to any entity; not subject
    to ownership checks). The shared constant is the canonical form.
  - Member: identity is the acting Member's id (entity-backed). Ownership-gated calls
    MUST use make_member_headers(member["id"]).
  - Instructor: identity is the acting Teacher's id (entity-backed). Ownership-gated
    reads MUST use make_instructor_headers(teacher["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque StudioManager, and for tests that don't exercise
# ownership (e.g. 404 / bad-payload / unauthorized-role scenarios).
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "studio_manager_headers": build_user_headers("studio-manager-1", "StudioManager"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
}


def make_studio_manager_headers(user_id: str = "studio-manager-1") -> dict:
    """StudioManager headers (opaque identity). The id is never compared to an entity."""
    return build_user_headers(user_id, "StudioManager")


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id whenever
    the call is ownership-gated (reservation/entitlement/enrollment writes and own reads)."""
    return build_user_headers(user_id, "Member")


def make_instructor_headers(user_id: str) -> dict:
    """For Instructor (entity_backed:Teacher). Pass the actual Teacher.id as user_id
    whenever the read is ownership-gated."""
    return build_user_headers(user_id, "Instructor")
