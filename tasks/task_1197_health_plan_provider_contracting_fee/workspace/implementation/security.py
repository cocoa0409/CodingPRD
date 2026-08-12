"""Authentication, role authorization and provider-ownership scoping."""

from flask import request

from errors import ApiError

ROLE_PLAN_ADMIN = "PlanAdmin"
ROLE_CONTRACT_MANAGER = "ContractManager"
ROLE_CONTRACT_LEGAL = "ContractLegal"
ROLE_CONFIG_ANALYST = "ConfigurationAnalyst"
ROLE_PAYMENT_INTEGRITY = "PaymentIntegrityAnalyst"
ROLE_PROVIDER_REP = "ProviderRep"

ALL_ROLES = [
    ROLE_PLAN_ADMIN,
    ROLE_CONTRACT_MANAGER,
    ROLE_CONTRACT_LEGAL,
    ROLE_CONFIG_ANALYST,
    ROLE_PAYMENT_INTEGRITY,
    ROLE_PROVIDER_REP,
]
INTERNAL_ROLES = ALL_ROLES[:5]  # every role except ProviderRep


def auth():
    """Validate X-User-ID / X-User-Role headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED", 401,
            "X-User-ID and X-User-Role headers are required and the role must be declared.",
        )
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE", 403,
            f"Role {role} is not permitted for this endpoint.",
        )


def check_ownership(role, user_id, provider_id):
    """ProviderRep scoping on the eight provider-owned read endpoints."""
    if role == ROLE_PROVIDER_REP and user_id != provider_id:
        raise ApiError(
            "ERR_FORBIDDEN_OWNERSHIP", 403,
            "ProviderRep may only read resources of their own provider chain.",
        )
