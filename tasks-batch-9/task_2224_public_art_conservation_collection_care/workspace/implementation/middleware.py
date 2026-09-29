"""Authentication, RBAC and ownership checks (PRD 2.1, 2.8 steps 1-2 and 8)."""

from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "CollectionsRegistrar",
    "ConditionSurveyor",
    "ChiefConservator",
    "ConservatorVendor",
    "MaintenanceCrew",
    "PublicArtManager",
    "FinanceOfficer",
    "ArtCommissionMember",
    "ArtistRepresentative",
)

ANY_ROLE = ROLES
FUNDING_ROLES = ("FinanceOfficer", "PublicArtManager", "ChiefConservator")


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if not role or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unknown role '%s'." % role)
    g.user_id = str(user_id).strip()
    g.user_role = role


def authorize(roles):
    if g.user_role not in roles:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role %s may not call this endpoint." % g.user_role,
        )


def endpoint(roles):
    """Decorator: authenticate, then authorize the declared role list."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(roles)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_owner(actual_owner_id):
    """Ownership for the two entity-backed roles (PRD 2.8 step 8)."""
    if g.user_id != actual_owner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
