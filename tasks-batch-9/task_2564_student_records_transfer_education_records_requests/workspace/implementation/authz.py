"""Authorization band helpers (PRD 2.1, 2.9 band 20).

Order inside the band is fixed: role permission, then rights transfer, then
guardianship identity, then segregation of duties, then district ownership.
"""

from common import ROLE_ELIGIBLE_STUDENT, ROLE_PARENT, err, user_id, user_role
from derive import refresh_eligibility

RIGHTS_HOLDER_ROLES = [ROLE_PARENT, ROLE_ELIGIBLE_STUDENT]


def rights_holder_guard(student_row):
    """Rights transfer then guardianship identity, for the five rights-holder ops."""
    role = user_role()
    refresh_eligibility(student_row)
    eligible = bool(student_row["is_eligible_student"])
    if role == ROLE_PARENT and eligible:
        err("ERR_RIGHTS_TRANSFERRED", 403,
            "Rights have transferred to the student; the guardian may no longer act.")
    if role == ROLE_ELIGIBLE_STUDENT and not eligible:
        err("ERR_RIGHTS_NOT_TRANSFERRED", 403,
            "Rights have not transferred to the student yet.")
    acting = user_id()
    if role == ROLE_PARENT:
        if acting != student_row["guardian_user_id"]:
            err("ERR_NOT_STUDENT_GUARDIAN", 403, "Acting user is not this student's guardian.")
    elif role == ROLE_ELIGIBLE_STUDENT:
        if acting != student_row["student_user_id"]:
            err("ERR_NOT_STUDENT_GUARDIAN", 403, "Acting user is not this student.")
    return role


def requester_role_value():
    return "PARENT" if user_role() == ROLE_PARENT else "ELIGIBLE_STUDENT"
