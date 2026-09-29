"""Authentication, role authorization, ownership and segregation-of-duties.

Header names and role values come from PRD 2.1: X-User-ID identifies the acting
user, X-User-Role names the role.
"""
from functools import wraps

from flask import g, request

from errors import ApiError

ROLE_HEADER = "X-User-Role"
USER_HEADER = "X-User-ID"

PROGRAM_ADMIN = "ProgramAdmin"
FIELD_INSPECTOR = "FieldInspector"
DETERMINATION_REVIEWER = "DeterminationReviewer"
PROCUREMENT_OFFICER = "ProcurementOfficer"
AWARD_AUTHORITY = "AwardAuthority"
FUNDING_OFFICER = "FundingOfficer"
CONTRACTOR = "Contractor"
OPERATOR = "Operator"

ALL_ROLES = (
    PROGRAM_ADMIN,
    FIELD_INSPECTOR,
    DETERMINATION_REVIEWER,
    PROCUREMENT_OFFICER,
    AWARD_AUTHORITY,
    FUNDING_OFFICER,
    CONTRACTOR,
    OPERATOR,
)

# The two entity-backed roles: X-User-ID is the id of a persisted row.
ENTITY_BACKED = (CONTRACTOR, OPERATOR)

STAFF_ROLES = (
    PROGRAM_ADMIN,
    FIELD_INSPECTOR,
    DETERMINATION_REVIEWER,
    PROCUREMENT_OFFICER,
    AWARD_AUTHORITY,
    FUNDING_OFFICER,
)


def unauthenticated(message):
    return ApiError("ERR_UNAUTHENTICATED", message)


def role():
    return getattr(g, "user_role", None)


def user_id():
    return getattr(g, "user_id", None)


def authenticate(needs_user_id):
    """PRD 2.10 step 1."""
    raw_role = request.headers.get(ROLE_HEADER)
    if raw_role is None or str(raw_role).strip() == "":
        raise unauthenticated("X-User-Role header is required.")
    raw_role = str(raw_role).strip()
    if raw_role not in ALL_ROLES:
        raise unauthenticated("X-User-Role '%s' is not a declared role." % raw_role)
    raw_user = request.headers.get(USER_HEADER)
    if raw_user is not None:
        raw_user = str(raw_user).strip()
        if raw_user == "":
            raw_user = None
    # Entity-backed roles always need their identity to resolve ownership.
    if (needs_user_id or raw_role in ENTITY_BACKED) and raw_user is None:
        raise unauthenticated("X-User-ID header is required for this endpoint.")
    g.user_role = raw_role
    g.user_id = raw_user
    return raw_role, raw_user


def authorize(allowed):
    """PRD 2.10 step 2."""
    if role() not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role %s is not authorized for this endpoint." % role(),
        )


def not_owner(message="Caller does not own the target resource."):
    return ApiError("ERR_NOT_RESOURCE_OWNER", message)


def sod(message="The acting user may not decide their own submission."):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", message)


def endpoint(roles, needs_user_id=False):
    """Decorator running authentication then role authorization."""
    def outer(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            authenticate(needs_user_id)
            authorize(roles)
            return fn(*args, **kwargs)
        return inner
    return outer
