"""Auth header extraction and role checking (PRD §2.1).

Every request must carry X-User-ID and X-User-Role. Missing either, or an
unrecognized role, yields ERR_UNAUTHENTICATED (401). A recognized role not
admitted to the endpoint yields ERR_UNAUTHORIZED (403). X-User-ID is opaque;
authorization is decided by role alone.
"""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {
    "PlatformAdmin",
    "RackPriceAnalyst",
    "AllocationManager",
    "TerminalOperator",
    "ExchangeCoordinator",
    "CreditAnalyst",
    "BillingClerk",
    "ContractAdministrator",
}

ALL_ROLES = sorted(ROLES)


def require_auth():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "Missing or invalid X-User-Role / X-User-ID headers",
        )
    return user_id, role


def require_roles(allowed):
    """Auth first (401), then endpoint role admission (403)."""
    user_id, role = require_auth()
    if role not in set(allowed):
        raise ApiError(
            ERR_UNAUTHORIZED,
            403,
            "Role {} is not permitted to invoke this endpoint".format(role),
        )
    return user_id, role
