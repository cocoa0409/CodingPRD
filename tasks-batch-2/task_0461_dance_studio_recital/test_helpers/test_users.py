"""Pre-built role headers for every role in the PRD.

Roles (PRD §2.1):
- StudioAdmin: opaque operator identity; X-User-ID is not tied to any entity.
- Anonymous: opaque; accepted only on family self-registration.
- Instructor: entity-backed; X-User-ID is the acting Instructor.id.
- Parent: entity-backed against the family; X-User-ID is the acting Family.id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that do not exercise ownership.
TEST_USERS = {
    # StudioAdmin is opaque: the shared constant is the canonical form.
    "admin_headers": build_user_headers("admin-operator-1", "StudioAdmin"),
    # Anonymous is opaque: canonical form for self-registration.
    "anonymous_headers": build_user_headers("anon-visitor-1", "Anonymous"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    "parent_headers": build_user_headers("test-parent-1", "Parent"),
}


def make_admin_headers() -> dict:
    """StudioAdmin (opaque). X-User-ID is an operator identifier, not an entity id."""
    return TEST_USERS["admin_headers"]


def make_anonymous_headers() -> dict:
    """Anonymous (opaque). Accepted only on POST /families self-registration."""
    return TEST_USERS["anonymous_headers"]


def make_instructor_headers(instructor_id: str) -> dict:
    """For Instructor (entity_backed:Instructor). Pass the actual Instructor.id as user_id
    whenever the call is identity-gated (marking/amending attendance)."""
    return build_user_headers(instructor_id, "Instructor")


def make_parent_headers(family_id: str) -> dict:
    """For Parent (entity_backed:Family). Pass the actual Family.id as user_id whenever the
    call is ownership-gated (acting on own student/enrollment/seat/costume-order/invoice/family)."""
    return build_user_headers(family_id, "Parent")


def make_role_headers(role: str, user_id: str) -> dict:
    """Generic builder for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
