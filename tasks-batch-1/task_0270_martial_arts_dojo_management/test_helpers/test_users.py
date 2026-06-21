"""Pre-built role headers for every role in the PRD (§2.1).

FrontDesk has an OPAQUE identity: X-User-ID is an audit-only staff string never
compared to any entity id, so the shared constant is the canonical form.

Instructor, ChiefInstructor and Member are ENTITY-BACKED: X-User-ID must be the
acting entity's id, and ownership/identity checks compare it against the resource's
foreign key. For ownership-gated calls use the per-instance builders below with the
actual entity id (e.g. make_member_headers(member["id"])). The shared constants for
those roles are a fallback for tests that do NOT exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # FrontDesk — opaque identity; shared constant is the canonical form.
    "front_desk_headers": build_user_headers("staff-front-desk-1", "FrontDesk"),
    # Entity-backed roles — shared constants are non-ownership fallbacks only.
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    "chief_instructor_headers": build_user_headers("test-chief-1", "ChiefInstructor"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_front_desk_headers(user_id="staff-front-desk-1") -> dict:
    """FrontDesk (opaque). Any non-empty string is accepted as the staff id."""
    return build_user_headers(user_id, "FrontDesk")


def make_instructor_headers(instructor_id: str) -> dict:
    """For Instructor (entity_backed:Instructor). Pass the actual Instructor.id
    whenever the call is ownership-gated."""
    return build_user_headers(instructor_id, "Instructor")


def make_chief_instructor_headers(instructor_id: str) -> dict:
    """For ChiefInstructor (entity_backed:Instructor with rank_level
    CHIEF_INSTRUCTOR). Pass the actual Instructor.id."""
    return build_user_headers(instructor_id, "ChiefInstructor")


def make_member_headers(member_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id whenever the
    call acts on the member's own resources."""
    return build_user_headers(member_id, "Member")
