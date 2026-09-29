"""Authentication and role-based access control (PRD 2.1, ladder steps 1-2).

The caller identifies itself with two headers: X-User-Role names the acting
role and X-User-ID carries the caller's identifier.  An absent role header is
an anonymous walk-up caller, admitted only where the Anonymous role is listed.
"""
from flask import request

from errors import ApiError

ROLE_PROGRAMMER = "Programmer"
ROLE_RIGHTS = "RightsManager"
ROLE_TECH = "TechnicalManager"
ROLE_BOX = "BoxOfficeManager"
ROLE_EXEC = "ExecutiveDirector"
ROLE_MEMBER = "Member"
ROLE_ANON = "Anonymous"

ALL_ROLES = (
    ROLE_PROGRAMMER, ROLE_RIGHTS, ROLE_TECH, ROLE_BOX, ROLE_EXEC,
    ROLE_MEMBER, ROLE_ANON,
)

# Every role that can read the public calendar.
PUBLIC_READ = (ROLE_PROGRAMMER, ROLE_RIGHTS, ROLE_TECH, ROLE_BOX, ROLE_EXEC,
               ROLE_MEMBER, ROLE_ANON)


def raw_role():
    value = request.headers.get("X-User-Role")
    if value is None:
        value = request.headers.get("X-Role")
    if value is not None:
        value = value.strip()
        if value == "":
            value = None
    return value


def user_id():
    value = request.headers.get("X-User-ID")
    if value is not None:
        value = value.strip()
        if value == "":
            value = None
    return value


def authorize(allowed_roles, require_user_id=False):
    """Ladder step 1 (ERR_UNAUTHENTICATED) then step 2 (ERR_FORBIDDEN_ROLE)."""
    role = raw_role()
    if role is None:
        if ROLE_ANON in allowed_roles:
            role = ROLE_ANON
        else:
            raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    elif role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role '%s' is not a declared role." % role)
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % role)
    uid = user_id()
    if require_user_id and not uid:
        raise ApiError("ERR_FORBIDDEN_ROLE", "X-User-ID is required on this endpoint.")
    return role, uid


def require_own_member(role, uid, member_id):
    """A Member acts only on their own records (PRD 2.1)."""
    if role == ROLE_MEMBER and member_id != uid:
        raise ApiError("ERR_FORBIDDEN_ROLE", "A Member may only act on their own records.")
