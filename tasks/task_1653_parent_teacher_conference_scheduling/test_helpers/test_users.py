"""Pre-built role headers for every role named in PRD 2.1.

`Teacher`, `FamilyGuardian` and `Interpreter` are entity-backed roles: their
`X-User-ID` must equal the acting Teacher / Family / Interpreter row's `id`,
so they need per-instance builders. The shared constants below are fallbacks
only for calls whose success does not depend on ownership. `SchoolAdmin` and
`FrontOfficeStaff` carry opaque operator identities that are never compared
to any row's `id`, so their shared constants are the canonical form.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque identities — the shared constant is the canonical form.
    "school_admin_headers": build_user_headers("test-admin-1", "SchoolAdmin"),
    "front_office_headers": build_user_headers("test-staff-1", "FrontOfficeStaff"),
    # Entity-backed identities — fallbacks for non-ownership tests only.
    "teacher_headers": build_user_headers("test-teacher-1", "Teacher"),
    "family_guardian_headers": build_user_headers("test-family-1", "FamilyGuardian"),
    "interpreter_headers": build_user_headers("test-interpreter-1", "Interpreter"),
}


def make_school_admin_headers(user_id: str = "test-admin-1") -> Dict[str, str]:
    return build_user_headers(user_id, "SchoolAdmin")


def make_front_office_headers(user_id: str = "test-staff-1") -> Dict[str, str]:
    return build_user_headers(user_id, "FrontOfficeStaff")


def make_teacher_headers(teacher_id: str) -> Dict[str, str]:
    """For Teacher (entity-backed). Pass the acting Teacher row's id whenever
    the call is ownership-gated (own slots, own bookings)."""
    return build_user_headers(teacher_id, "Teacher")


def make_family_guardian_headers(family_id: str) -> Dict[str, str]:
    """For FamilyGuardian (entity-backed). Pass the acting Family row's id
    whenever the call is ownership-gated (own family/students/bookings/entries)."""
    return build_user_headers(family_id, "FamilyGuardian")


def make_interpreter_headers(interpreter_id: str) -> Dict[str, str]:
    """For Interpreter (entity-backed). Pass the acting Interpreter row's id
    whenever the call is ownership-gated (own requests)."""
    return build_user_headers(interpreter_id, "Interpreter")


# Headers carrying neither X-User-ID nor X-User-Role — used to exercise the
# authentication rung directly.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
