"""Auth: X-User-ID / X-User-Role header extraction and role gating."""
from flask import request, g

from errors import ApiError

ROLES = ["FundAccountant", "FundController", "PricingCommittee", "ComplianceOfficer"]

ALL_ROLES = list(ROLES)


def get_context():
    """Validate the two auth headers; populate flask.g with caller identity."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-ID and X-User-Role headers are required and role must be a declared role")
    g.user_id = uid
    g.user_role = role
    return uid, role


def require_roles(allowed):
    role = getattr(g, "user_role", None)
    if role is None:
        get_context()
        role = g.user_role
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Role %s is not permitted on this endpoint" % role)
