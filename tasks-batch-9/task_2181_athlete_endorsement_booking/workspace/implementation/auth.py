"""Caller identity and role authorisation (PRD section 2.1)."""

from flask import request

from errors import ApiError

ROLES = ("TalentAgent", "BrandRep", "Athlete", "ComplianceOfficer", "FinanceManager")
ALL_ROLES = list(ROLES)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a declared role")
    return Caller(str(user_id).strip(), role)


def require(*roles):
    """Ladder steps 1 and 2: authenticate, then authorise the endpoint role."""
    caller = authenticate()
    allowed = roles[0] if len(roles) == 1 and isinstance(roles[0], (list, tuple)) else roles
    if caller.role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", "role %s may not call this endpoint" % caller.role)
    return caller


def own_brand(caller, brand_id):
    if caller.role == "BrandRep" and caller.user_id != brand_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "caller does not own this brand resource")


def own_athlete(caller, athlete_id):
    if caller.role == "Athlete" and caller.user_id != athlete_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "caller does not own this athlete resource")
