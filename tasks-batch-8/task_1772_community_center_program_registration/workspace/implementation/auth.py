"""Authentication and role authorization (PRD 2.1, validation priorities 1-2).

Every call must carry X-User-ID and X-User-Role; the role must name one of the
six declared roles, else ERR_UNAUTHENTICATED.  Each endpoint then restricts to
its declared role list, else ERR_UNAUTHORIZED_ROLE.  Entity-backed identity
(HouseholdManager -> Household.id, Instructor -> Instructor.id) is enforced at
the routes the PRD pins it to.
"""
from flask import request

from errors import raise_err

ROLES = [
    "HouseholdManager",
    "ProgramCoordinator",
    "FrontDeskStaff",
    "Instructor",
    "ScholarshipReviewer",
    "FinanceOfficer",
]

ALL_ROLES = list(ROLES)


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and must name a declared role",
        )
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise_err(
            "ERR_UNAUTHORIZED_ROLE",
            "Role %s is not authorized for this operation" % role,
        )
