"""Authentication / authorization middleware (PRD section 2.1).

Every call requires X-User-ID and X-User-Role headers. Role names are spelled
exactly: PlatformAdmin, ProgramAdmin, IntakeSpecialist, ComplianceOfficer,
LeaseManager, Inspector, Household. When the role is Household, X-User-ID is
the id of the acting Household resource; for every other role it is opaque.
"""
import functools

from flask import g, request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED,
)

ROLES = {
    "PlatformAdmin",
    "ProgramAdmin",
    "IntakeSpecialist",
    "ComplianceOfficer",
    "LeaseManager",
    "Inspector",
    "Household",
}

ALL_ROLES = sorted(ROLES)


def current_user():
    return g.user_id, g.user_role


def require(allowed_roles):
    """Validate the user-context headers, then enforce the role list."""
    allowed = set(allowed_roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not isinstance(uid, str) or not role or role not in ROLES:
                raise ApiError(
                    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    400,
                    "X-User-ID and X-User-Role headers must be present and well-formed",
                )
            if role not in allowed:
                raise ApiError(
                    ERR_UNAUTHORIZED,
                    403,
                    "Role %s is not permitted to invoke this operation" % role,
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_household_owner(household_id):
    """When the caller acts as Household, its X-User-ID must match the
    household FK of the resource being touched. No-op for other roles."""
    if g.user_role == "Household" and g.user_id != household_id:
        raise ApiError(
            ERR_UNAUTHORIZED,
            403,
            "Household callers may only act on their own resources",
        )
