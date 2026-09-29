"""Authentication and RBAC (PRD 2.1)."""

from flask import request

from errors import ApiError

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_FACULTY = "Faculty"
ROLE_REGISTRAR = "Registrar"
ROLE_BURSAR = "BursarOfficer"
ROLE_STUDENT = "Student"
ROLE_COMPLIANCE = "ComplianceOfficer"

ALL_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_FACULTY,
    ROLE_REGISTRAR,
    ROLE_BURSAR,
    ROLE_STUDENT,
    ROLE_COMPLIANCE,
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(*allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return Actor(user_id, role)
