"""Authentication, RBAC and resource-ownership enforcement (PRD 2.1 / 2.5)."""
from flask import request

from errors import ApiError

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

REPRESENTATIVE = "OutfitterRepresentative"
SPECIALIST = "PermitSpecialist"
OFFICER = "AuthorizedOfficer"
ADMIN = "ProgramAdministrator"

ROLES = (REPRESENTATIVE, SPECIALIST, OFFICER, ADMIN)
ANY_ROLE = ROLES


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_representative(self):
        return self.role == REPRESENTATIVE


def authenticate(allowed_roles, mutating=True):
    """Priority 1 (authentication) then priority 2 (authorization)."""
    role = request.headers.get(HEADER_USER_ROLE)
    user_id = request.headers.get(HEADER_USER_ID)
    if role is None or not role.strip() or role.strip() not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "missing or invalid %s" % HEADER_USER_ROLE)
    role = role.strip()
    if mutating and (user_id is None or not user_id.strip()):
        raise ApiError("ERR_UNAUTHENTICATED", "missing %s" % HEADER_USER_ID)
    user_id = user_id.strip() if user_id else None
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "role %s may not perform this action" % role)
    return Caller(user_id, role)


def require_owner(caller, outfitter_id):
    """Priority 4 -- an OutfitterRepresentative acts only for its own outfitter."""
    if caller.role != REPRESENTATIVE:
        return
    if outfitter_id is None or caller.user_id != outfitter_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "caller does not own this resource")
