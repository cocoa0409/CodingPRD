"""Auth header extraction and role checks (PRD 2.1, pipeline layers 1-2).

Headers: X-User-ID and X-User-Role. The five declared roles are Applicant,
PreservationStaff, Commissioner, CouncilMember, EnforcementOfficer. A request
missing either header, or carrying a role outside the declared set, fails with
ERR_UNAUTHENTICATED. Role membership in an endpoint's allowed list, and
Applicant ownership (X-User-ID == resource owner_id), fail with
ERR_FORBIDDEN_ROLE.
"""
from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ALL_ROLES = [
    "Applicant",
    "PreservationStaff",
    "Commissioner",
    "CouncilMember",
    "EnforcementOfficer",
]
_ROLE_SET = set(ALL_ROLES)


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Pipeline layer 1 (authentication): headers present, role declared."""
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not isinstance(user_id, str) or not isinstance(role, str):
        raise_error(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role headers are required")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role or role not in _ROLE_SET:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-ID and X-User-Role headers must be present and the role "
                    "must be one of the declared roles")
    return Caller(user_id, role)


def check_role_allowed(caller: Caller, allowed_roles):
    """Pipeline layer 2 (authorization): role membership in the endpoint's list."""
    if caller.role not in allowed_roles:
        raise_error(ERR_FORBIDDEN_ROLE,
                    f"role {caller.role} is not authorized for this endpoint")


def check_applicant_ownership(caller: Caller, owner_id):
    """Pipeline layer 2 (authorization): an Applicant may act only on resources
    whose owner foreign key equals the caller's X-User-ID."""
    if caller.role == "Applicant" and caller.user_id != owner_id:
        raise_error(ERR_FORBIDDEN_ROLE,
                    "applicant may only act on their own applications or appeals")


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    check_role_allowed(caller, allowed_roles)
    return caller
