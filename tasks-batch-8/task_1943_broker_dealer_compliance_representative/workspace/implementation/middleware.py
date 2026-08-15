"""Auth header extraction and role checks (PRD 2.1, validation priorities 1-2).

The system recognizes exactly five role values: FirmAdmin, ComplianceAnalyst,
CompliancePrincipal, RegisteredRep, and Any. Missing headers or an unrecognized
role value -> ERR_MISSING_USER_CONTEXT (400). Role membership failures ->
ERR_FORBIDDEN_ROLE (403).

When X-User-Role is RegisteredRep, X-User-ID is the id of the acting
RegisteredRepresentative (entity-backed identity). For all other roles the id is
an opaque operator identifier, never compared to entity ids.
"""
from flask import request

from errors import raise_error, ERR_MISSING_USER_CONTEXT, ERR_FORBIDDEN_ROLE

ALL_ROLES = {"FirmAdmin", "ComplianceAnalyst", "CompliancePrincipal", "RegisteredRep", "Any"}
# GET endpoints are declared roles: [Any] — every authenticated caller may read.
READ_ROLES = sorted(ALL_ROLES)


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: header presence + recognized role value."""
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    user_id = user_id.strip() if isinstance(user_id, str) else ""
    role = role.strip() if isinstance(role, str) else ""
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(ERR_MISSING_USER_CONTEXT,
                    "X-User-ID and X-User-Role headers are required and the role must be recognized")
    return Caller(user_id, role)


def require_role(caller: Caller, allowed_roles):
    """Priority 2: endpoint role membership."""
    if caller.role not in allowed_roles:
        raise_error(ERR_FORBIDDEN_ROLE,
                    f"role {caller.role} is not authorized for this endpoint")


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    require_role(caller, allowed_roles)
    return caller
