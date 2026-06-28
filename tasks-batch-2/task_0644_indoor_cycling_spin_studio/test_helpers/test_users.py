"""Pre-built role headers for every role in the PRD.

StudioManager and Anonymous are opaque identities — their X-User-ID is not matched
against any stored entity, so the shared constants are always safe.

Member and Instructor are entity-backed: their X-User-ID must equal the acting
entity's id for ownership checks to pass. Use the per-instance builders
(make_member_headers / make_instructor_headers) with the real entity id whenever
a call is ownership-gated. The shared TEST_USERS entries for these roles are only
safe for tests that do NOT depend on owning the subject resource (e.g. 403/404
on a missing resource, or pure RBAC-role denials).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "studio_manager_headers": build_user_headers("test-manager-1", "StudioManager"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # Entity-backed roles — shared constant is a fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
}


def make_member_headers(user_id: str) -> dict:
    """For a Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (book/cancel/waitlist/retail on own data)."""
    return build_user_headers(user_id, "Member")


def make_instructor_headers(user_id: str) -> dict:
    """For an Instructor (entity_backed:Instructor). Pass the actual Instructor.id
    as user_id whenever the call is ownership-gated (check-in / shoe-return on own
    sessions)."""
    return build_user_headers(user_id, "Instructor")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    """StudioManager is opaque; any well-formed id works."""
    return build_user_headers(user_id, "StudioManager")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    return build_user_headers(user_id, "Anonymous")
