"""Pre-built role headers for every role in the PRD.

Two roles are opaque operator identities (FacilityManager, FrontDesk): their
X-User-ID is not tied to any persisted entity, so a shared constant is the
canonical form. Two roles are entity-backed (Member, Instructor): for any
ownership-gated call, the per-instance builder MUST be used with the actual
entity id, because ownership checks compare the resource's member_id /
instructor_id to X-User-ID.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# - Opaque roles (manager, front_desk): canonical, used everywhere.
# - Entity-backed roles (member, instructor): only for tests that do NOT exercise
#   ownership (e.g. 403-on-forbidden-role, 404-on-missing-resource).
TEST_USERS = {
    "manager_headers": build_user_headers("test-manager-1", "FacilityManager"),
    "front_desk_headers": build_user_headers("test-frontdesk-1", "FrontDesk"),
    "member_headers": build_user_headers("test-member-1", "Member"),
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
}


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    """FacilityManager is opaque; user_id is recorded but never matched to an entity."""
    return build_user_headers(user_id, "FacilityManager")


def make_front_desk_headers(user_id: str = "test-frontdesk-1") -> dict:
    """FrontDesk is opaque; user_id is recorded but never matched to an entity."""
    return build_user_headers(user_id, "FrontDesk")


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (booking/enrollment/waiver on self)."""
    return build_user_headers(user_id, "Member")


def make_instructor_headers(user_id: str) -> dict:
    """For Instructor (entity_backed:Instructor). Pass the actual Instructor.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Instructor")
