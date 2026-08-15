"""Auth header extraction and role checking (PRD 2.1).

Headers: X-User-ID (identity) and X-User-Role (role). MerchantUser identity is
entity-backed by Merchant.id; other roles are opaque operator identifiers.
"""

from flask import g, request

from errors import ApiError

ROLES = ("AcquirerOps", "MerchantUser", "RiskOfficer", "FinanceOps")


def auth_ctx():
    """Priority 1: headers present and non-empty -> else ERR_UNAUTHENTICATED (401)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or not uid.strip() or not role.strip():
        raise ApiError(401, "ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers must be present and non-empty")
    g.uid = uid
    g.role = role


def require_roles(*roles):
    """Priority 2: role admitted by endpoint -> else ERR_FORBIDDEN_ROLE (403)."""
    if g.role not in roles:
        raise ApiError(403, "ERR_FORBIDDEN_ROLE", "Role '%s' is not permitted for this endpoint" % g.role)


def is_merchant_user():
    return g.role == "MerchantUser"
