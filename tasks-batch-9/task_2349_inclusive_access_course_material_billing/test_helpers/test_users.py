"""Acting-operator headers for the six roles of PRD §2.1.

Five of the six roles are opaque operator identities — ``ProgramAdmin``,
``Faculty``, ``Registrar``, ``BursarOfficer`` and ``ComplianceOfficer`` — so a
default id per role is enough for calls that are not ownership-scoped.  Two
kinds of call must always name a concrete operator instead:

* ``Student`` calls, because PRD §2.1 requires the acting ``X-User-ID`` to equal
  the ``student_id`` behind the charge — use ``make_student_headers(student_id)``.
* ``Faculty`` calls on adoptions, because the acting ``X-User-ID`` must equal the
  section's ``instructor_user_id`` — use ``make_faculty_headers("fac-1")``.
* ``ProgramAdmin`` approvals, because segregation of duties compares the
  approver's ``X-User-ID`` with the submitter's — use
  ``make_program_admin_headers("pa-2")`` when a distinct operator is needed.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Default operator ids per opaque role.
PROGRAM_ADMIN_USER_ID = "pa-1"
SECOND_PROGRAM_ADMIN_USER_ID = "pa-2"
FACULTY_USER_ID = "fac-1"
REGISTRAR_USER_ID = "reg-1"
BURSAR_OFFICER_USER_ID = "bo-1"
COMPLIANCE_OFFICER_USER_ID = "co-1"


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.PROGRAM_ADMIN.value)


def make_faculty_headers(user_id: str = FACULTY_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.FACULTY.value)


def make_registrar_headers(user_id: str = REGISTRAR_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.REGISTRAR.value)


def make_bursar_officer_headers(user_id: str = BURSAR_OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.BURSAR_OFFICER.value)


def make_compliance_officer_headers(user_id: str = COMPLIANCE_OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def make_student_headers(student_id: str) -> dict:
    """Headers for a ``Student`` acting as the student whose id is ``student_id``.

    PRD §2.1 scopes every student-facing operation by identity, so this must be
    threaded from the created ``Student`` resource — there is no shared default.
    """
    return build_user_headers(student_id, UserRole.STUDENT.value)


def make_role_headers(role: str, user_id: str) -> dict:
    """Headers for an arbitrary declared role and operator id."""
    return build_user_headers(user_id, role)


TEST_USERS = {
    "program_admin": make_program_admin_headers(),
    "second_program_admin": make_program_admin_headers(SECOND_PROGRAM_ADMIN_USER_ID),
    "faculty": make_faculty_headers(),
    "registrar": make_registrar_headers(),
    "bursar_officer": make_bursar_officer_headers(),
    "compliance_officer": make_compliance_officer_headers(),
}

# Headers carrying no identity at all — used to probe PRD §2.1 authentication.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
