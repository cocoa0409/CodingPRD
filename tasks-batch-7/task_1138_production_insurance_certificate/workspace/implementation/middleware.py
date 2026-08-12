"""Auth header extraction and role-based access control (PRD section 2.1).

Headers: X-User-Role (one of the eight declared roles) and X-User-ID
(opaque operator identifier). Missing/malformed -> ERR_UNAUTHENTICATED (401).
Well-formed but unauthorized for the endpoint -> ERR_FORBIDDEN (403).
"""

from flask import request

from errors import err

ROLES = {
    "BrokerAgent",
    "ProductionManager",
    "UnderwriterAgent",
    "ClaimsAdjuster",
    "ClearanceCounsel",
    "SuretyUnderwriter",
    "ExternalAuditor",
    "PlatformOperator",
}

ALL_ROLES = sorted(ROLES)


def current_actor():
    """Validate auth headers; return (user_id, role)."""
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-Role header")
    user_id = request.headers.get("X-User-ID")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-ID header")
    return user_id, role


def require_roles(allowed):
    """Validate auth headers and endpoint role authorization.

    Returns (user_id, role) for the caller.
    """
    user_id, role = current_actor()
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role '%s' is not authorized for this endpoint" % role)
    return user_id, role
