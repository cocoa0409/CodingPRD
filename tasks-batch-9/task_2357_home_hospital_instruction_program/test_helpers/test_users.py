"""Pre-built role headers for every role in the PRD (§2.1).

`ProgramAdministrator`, `CaseManager` and `NurseReviewer` bind `X-User-ID` to an
opaque operator identifier, so a shared constant is the canonical form for
those three.

`HomeboundTeacher` and `ClassroomTeacher` bind `X-User-ID` to the `id` of the
acting `Teacher`. Every ownership-gated call for those two roles MUST use the
per-instance builder with the real teacher's `id`; the shared constants below
exist only for calls where no ownership comparison happens (unauthenticated /
unauthorized / not-found probes).
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers.
PROGRAM_ADMINISTRATOR_USER_ID = "pa-001"
CASE_MANAGER_USER_ID = "cm-001"
SECOND_CASE_MANAGER_USER_ID = "cm-002"
NURSE_REVIEWER_USER_ID = "nr-001"
SHARED_OPERATOR_USER_ID = "u-777"

TEST_USERS = {
    "program_administrator_headers": build_user_headers(
        PROGRAM_ADMINISTRATOR_USER_ID, "ProgramAdministrator"
    ),
    "case_manager_headers": build_user_headers(CASE_MANAGER_USER_ID, "CaseManager"),
    "second_case_manager_headers": build_user_headers(
        SECOND_CASE_MANAGER_USER_ID, "CaseManager"
    ),
    "nurse_reviewer_headers": build_user_headers(
        NURSE_REVIEWER_USER_ID, "NurseReviewer"
    ),
    # entity_backed roles: fallback constants for non-ownership probes only.
    "homebound_teacher_headers": build_user_headers(
        "unbound-homebound-teacher", "HomeboundTeacher"
    ),
    "classroom_teacher_headers": build_user_headers(
        "unbound-classroom-teacher", "ClassroomTeacher"
    ),
}

PA_HEADERS = TEST_USERS["program_administrator_headers"]
CM_HEADERS = TEST_USERS["case_manager_headers"]
CM2_HEADERS = TEST_USERS["second_case_manager_headers"]
NR_HEADERS = TEST_USERS["nurse_reviewer_headers"]


def make_program_administrator_headers(user_id: str) -> dict:
    """For `ProgramAdministrator` (opaque operator identifier)."""
    return build_user_headers(user_id, "ProgramAdministrator")


def make_case_manager_headers(user_id: str) -> dict:
    """For `CaseManager` (opaque operator identifier)."""
    return build_user_headers(user_id, "CaseManager")


def make_nurse_reviewer_headers(user_id: str) -> dict:
    """For `NurseReviewer` (opaque operator identifier)."""
    return build_user_headers(user_id, "NurseReviewer")


def make_homebound_teacher_headers(teacher_id: str) -> dict:
    """For `HomeboundTeacher`: pass the acting `Teacher`'s `id` as `X-User-ID`."""
    return build_user_headers(teacher_id, "HomeboundTeacher")


def make_classroom_teacher_headers(teacher_id: str) -> dict:
    """For `ClassroomTeacher`: pass the acting `Teacher`'s `id` as `X-User-ID`."""
    return build_user_headers(teacher_id, "ClassroomTeacher")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary user id / role pair, including roles outside the declared five."""
    return build_user_headers(user_id, role)
