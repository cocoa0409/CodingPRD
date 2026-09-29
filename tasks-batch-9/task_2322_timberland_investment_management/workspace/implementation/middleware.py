"""Authentication and role authorization (PRD 2.1, precedence steps 1 and 2)."""

from flask import g, request

from errors import ApiError

ROLES = (
    "FundAdmin",
    "AcquisitionAnalyst",
    "InvestmentCommittee",
    "ForestManager",
    "CertificationAuditor",
    "CarbonDeveloper",
    "IndependentAppraiser",
)

ANY_ROLE = ROLES


def authenticate():
    """Step 1: both headers present and the role one of the seven."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def authorize(*allowed):
    """Step 2: the acting role appears in the endpoint's role list."""
    if g.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


def require(*allowed):
    """Authenticate, then authorize; returns the acting user id."""
    user_id, _role = authenticate()
    authorize(*allowed)
    return user_id


def authorize_action(action, permitted_by_action):
    """Action-granular authorization for endpoints with an `action` field."""
    allowed = permitted_by_action.get(action)
    if allowed is not None and g.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


def user_id():
    return g.user_id


def role():
    return g.role
