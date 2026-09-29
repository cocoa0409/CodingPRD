"""Caller identities.

PRD 2.1 authenticates on ``X-User-ID`` and authorises on ``X-User-Role``.
Two roles are entity-backed: a ``ProgramDean``'s ``X-User-ID`` must equal the
``Program.id`` they own, and an ``Instructor``'s must equal their own
``FacultyMember.id``.  Those identities therefore cannot be pre-baked and are
built per test from the entity the fixture just created.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque-identity roles: any stable identifier works.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin": build_user_headers("admin-01", Role.SYSTEM_ADMIN.value),
    "registrar": build_user_headers("registrar-01", Role.REGISTRAR_OFFICER.value),
    "analyst": build_user_headers("analyst-01", Role.CREDENTIAL_ANALYST.value),
    "analyst_2": build_user_headers("analyst-02", Role.CREDENTIAL_ANALYST.value),
    "liaison": build_user_headers("liaison-01", Role.ACCREDITATION_LIAISON.value),
    "liaison_2": build_user_headers("liaison-02", Role.ACCREDITATION_LIAISON.value),
    "reviewer": build_user_headers("reviewer-01", Role.ACCREDITOR_REVIEWER.value),
    # One human wearing two hats, used to exercise segregation of duties.
    "shared_analyst": build_user_headers("shared-user-1", Role.CREDENTIAL_ANALYST.value),
    "shared_liaison": build_user_headers(
        "shared-user-1", Role.ACCREDITATION_LIAISON.value
    ),
}

ADMIN_ID = "admin-01"
REGISTRAR_ID = "registrar-01"
ANALYST_ID = "analyst-01"
ANALYST_2_ID = "analyst-02"
LIAISON_ID = "liaison-01"
LIAISON_2_ID = "liaison-02"
REVIEWER_ID = "reviewer-01"
SHARED_USER_ID = "shared-user-1"


def make_program_dean_headers(program_id: str) -> Dict[str, str]:
    """A ProgramDean acts as the program itself (PRD 2.1)."""
    return build_user_headers(program_id, Role.PROGRAM_DEAN.value)


def make_instructor_headers(faculty_member_id: str) -> Dict[str, str]:
    """An Instructor acts as their own faculty record (PRD 2.1)."""
    return build_user_headers(faculty_member_id, Role.INSTRUCTOR.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    return build_user_headers(user_id, role)


def anonymous_headers(role: str) -> Dict[str, str]:
    """Headers carrying an empty ``X-User-ID`` for the PRD 2.1 401 probe."""
    return build_user_headers("", role)
