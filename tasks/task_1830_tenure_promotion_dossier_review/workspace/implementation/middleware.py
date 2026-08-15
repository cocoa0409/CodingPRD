"""Auth header extraction and role checks (PRD §2.1, validation priorities 1-2).

X-User-ID semantics by role (PRD §2.1):
- Candidate: the id of the acting Candidate entity
- CommitteeChair / CommitteeVoter: the id of the acting CommitteeMember entity
- ExternalReviewer: the id of the acting ExternalReviewer entity
- ProvostOfficer / AppealOfficer / RecordsOfficer / SystemAdmin: opaque operator
  identifiers, recorded but never compared to any entity id.
"""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
)

ALL_ROLES = {
    "ProvostOfficer",
    "Candidate",
    "CommitteeChair",
    "CommitteeVoter",
    "ExternalReviewer",
    "AppealOfficer",
    "RecordsOfficer",
    "SystemAdmin",
}

# The pseudo-role "Any" (read endpoints) covers every authenticated principal.
ALL_READ_ROLES = sorted(ALL_ROLES)


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-ID and X-User-Role present and non-empty."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "" or role is None or str(role).strip() == "":
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must both be present and non-empty",
        )
    return Caller(str(user_id).strip(), str(role).strip())


def check_role_allowed(caller: Caller, allowed_roles):
    """Priority 2: role membership in the endpoint's declared role set.

    An unrecognized role value is not a declared principal, so it is not
    permitted anywhere — including "Any" read endpoints.
    """
    if caller.role not in ALL_ROLES or caller.role not in allowed_roles:
        raise_error(
            ERR_FORBIDDEN_ROLE,
            f"role {caller.role} is not authorized for this endpoint",
        )


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    check_role_allowed(caller, allowed_roles)
    return caller
