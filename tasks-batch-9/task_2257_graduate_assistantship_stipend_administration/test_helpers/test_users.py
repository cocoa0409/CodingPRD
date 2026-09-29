"""Pre-built role headers for every role the PRD declares.

Four of the five roles carry an opaque identity, so a shared constant is the
canonical form for them.  ``StudentUser`` is the one entity-backed role: its
``X-User-ID`` is the ``id`` of the acting ``GraduateStudent``, so ownership-gated
calls MUST use :func:`make_student_user_headers` with the real student id.
"""
from prd_bench_local_runner.testing import build_user_headers

GRAD_SCHOOL_ADMIN_USER_ID = "user-gs-1"
SECOND_GRAD_SCHOOL_ADMIN_USER_ID = "user-gs-2"
DEPARTMENT_ADMIN_USER_ID = "user-dept-1"
GRANT_ACCOUNTANT_USER_ID = "user-ga-1"
FACULTY_SUPERVISOR_USER_ID = "user-fac-7"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "grad_school_admin_headers": build_user_headers(
        GRAD_SCHOOL_ADMIN_USER_ID, "GradSchoolAdmin"
    ),
    "second_grad_school_admin_headers": build_user_headers(
        SECOND_GRAD_SCHOOL_ADMIN_USER_ID, "GradSchoolAdmin"
    ),
    "department_admin_headers": build_user_headers(
        DEPARTMENT_ADMIN_USER_ID, "DepartmentAdmin"
    ),
    "grant_accountant_headers": build_user_headers(
        GRANT_ACCOUNTANT_USER_ID, "GrantAccountant"
    ),
    "faculty_supervisor_headers": build_user_headers(
        FACULTY_SUPERVISOR_USER_ID, "FacultySupervisor"
    ),
    # Entity-backed role — fallback for non-ownership tests only.
    "student_user_headers": build_user_headers(
        "00000000-0000-0000-0000-0000000000ff", "StudentUser"
    ),
}

GS_ADMIN = TEST_USERS["grad_school_admin_headers"]
GS_ADMIN_2 = TEST_USERS["second_grad_school_admin_headers"]
DEPT_ADMIN = TEST_USERS["department_admin_headers"]
GRANT_ACCOUNTANT = TEST_USERS["grant_accountant_headers"]
FACULTY = TEST_USERS["faculty_supervisor_headers"]


def make_grad_school_admin_headers(user_id: str) -> dict:
    """For a GradSchoolAdmin acting under a specific operator identifier."""
    return build_user_headers(user_id, "GradSchoolAdmin")


def make_department_admin_headers(user_id: str) -> dict:
    """For a DepartmentAdmin acting under a specific operator identifier."""
    return build_user_headers(user_id, "DepartmentAdmin")


def make_grant_accountant_headers(user_id: str) -> dict:
    """For a GrantAccountant acting under a specific operator identifier."""
    return build_user_headers(user_id, "GrantAccountant")


def make_faculty_supervisor_headers(user_id: str) -> dict:
    """For a FacultySupervisor acting under a specific operator identifier."""
    return build_user_headers(user_id, "FacultySupervisor")


def make_student_user_headers(student_id: str) -> dict:
    """For a StudentUser: pass the acting GraduateStudent's own ``id``.

    Every ownership check compares the addressed resource's ``student_id`` to
    ``X-User-ID``, so an ownership-gated call must carry the real row id.
    """
    return build_user_headers(student_id, "StudentUser")


def headers_without_identity() -> dict:
    """Headers carrying neither ``X-User-ID`` nor ``X-User-Role``."""
    return {"Content-Type": "application/json"}
