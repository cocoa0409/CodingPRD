"""Pre-built role headers for every role in the PRD (§2.1).

For entity-backed roles (District504Director, Section504Coordinator, Teacher,
SchoolPrincipal) `X-User-ID` is the `id` of the acting StaffMember — the
per-instance builders MUST be used for any call whose ownership, attribution,
or segregation check compares against a StaffMember id. The shared constants
in TEST_USERS are safe only for tests that do not exercise ownership
(e.g. 400/404/403-denial probes) and for the Parent role (opaque identity).
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import BOOTSTRAP_DIRECTOR_ID

# Shared constants — safe for opaque Parent identity, bootstrap admin calls,
# and denial probes that never depend on matching a real StaffMember id.
TEST_USERS = {
    "director_headers": build_user_headers(BOOTSTRAP_DIRECTOR_ID, "District504Director"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "Section504Coordinator"),
    "teacher_headers": build_user_headers("test-teacher-1", "Teacher"),
    "principal_headers": build_user_headers("test-principal-1", "SchoolPrincipal"),
    "parent_headers": build_user_headers("test-parent-1", "Parent"),
}


def make_director_headers(user_id: str) -> dict:
    """District504Director (entity-backed by StaffMember). Pass the acting
    StaffMember.id whenever the call is attribution- or segregation-gated."""
    return build_user_headers(user_id, "District504Director")


def make_coordinator_headers(user_id: str) -> dict:
    """Section504Coordinator (entity-backed by StaffMember). Pass the acting
    StaffMember.id whenever the call is attribution- or segregation-gated."""
    return build_user_headers(user_id, "Section504Coordinator")


def make_teacher_headers(user_id: str) -> dict:
    """Teacher (entity-backed by StaffMember). Pass the acting StaffMember.id —
    acknowledgment rows are ownership-checked against it (PRD §2.9)."""
    return build_user_headers(user_id, "Teacher")


def make_principal_headers(user_id: str) -> dict:
    """SchoolPrincipal (entity-backed by StaffMember)."""
    return build_user_headers(user_id, "SchoolPrincipal")


def make_parent_headers(parent_ref: str) -> dict:
    """Parent identity is opaque: X-User-ID is not tied to any entity (PRD §2.1)."""
    return build_user_headers(parent_ref, "Parent")


def headers_missing_user_id(role: str = "District504Director") -> dict:
    """Well-formed role header with X-User-ID absent (PRD §2.1 400 probe)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
