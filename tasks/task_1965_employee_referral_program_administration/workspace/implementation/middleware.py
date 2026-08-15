"""Auth extraction (pipeline step 1) and role authorization (step 4)."""

from flask import request, g

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = (
    "PlatformAdmin",
    "TalentAdmin",
    "Recruiter",
    "HiringManager",
    "Employee",
    "PayrollProcessor",
    "ComplianceOfficer",
)

ALL_ROLES = list(ROLES)


def authenticate():
    """Pipeline step 1: X-User-Role and X-User-ID present; role recognized."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "Missing or unrecognized X-User-Role / X-User-ID headers")
    g.user_id = user_id
    g.role = role


def require_role(*roles):
    """Pipeline step 4: caller's role is listed for the endpoint."""
    if g.role not in roles:
        raise ApiError(ERR_FORBIDDEN, 403, "Role %s is not authorized for this endpoint" % g.role)


def user_id():
    return g.user_id


def role():
    return g.role
