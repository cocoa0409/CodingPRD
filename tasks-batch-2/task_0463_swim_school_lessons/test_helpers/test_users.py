"""Pre-built role headers for every role in the PRD (Section 2.1).

SchoolAdmin and BillingAdmin act under opaque identities; their X-User-ID is
never compared to any entity id, so a shared constant is the canonical form.

Instructor and Parent act under entity-backed identities; their X-User-ID is
the id of the acting Instructor / Parent and ownership checks compare a
resource's instructor/parent foreign key to that id. Tests whose success
depends on ownership MUST use make_instructor_headers(...) /
make_parent_headers(...) threaded with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles (canonical) + entity-backed fallbacks for
# tests that do NOT exercise ownership (e.g. 400-on-bad-payload, 404-on-missing
# resource, RBAC permission denials).
TEST_USERS = {
    "school_admin_headers": build_user_headers("test-school-admin-1", "SchoolAdmin"),
    "billing_admin_headers": build_user_headers("test-billing-admin-1", "BillingAdmin"),
    # entity_backed fallbacks — only safe where ownership is not under test.
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    "parent_headers": build_user_headers("test-parent-1", "Parent"),
}


def make_school_admin_headers() -> dict:
    """SchoolAdmin (opaque). Identity is not entity-backed."""
    return TEST_USERS["school_admin_headers"]


def make_billing_admin_headers() -> dict:
    """BillingAdmin (opaque). Identity is not entity-backed."""
    return TEST_USERS["billing_admin_headers"]


def make_instructor_headers(instructor_id: str) -> dict:
    """For Instructor (entity_backed:Instructor). Pass the actual Instructor.id
    so the server's ownership checks (assigned teacher of the session) pass."""
    return build_user_headers(instructor_id, "Instructor")


def make_parent_headers(parent_id: str) -> dict:
    """For Parent (entity_backed:Parent). Pass the actual Parent.id so the
    server's ownership checks (parent of the student / enrollment) pass."""
    return build_user_headers(parent_id, "Parent")
