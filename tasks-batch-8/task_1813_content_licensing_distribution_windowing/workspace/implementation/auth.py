"""Auth: X-User-ID / X-User-Role extraction and role checks (PRD §2.1)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLE_RIGHTS_MANAGER = "RightsManager"
ROLE_PLATFORM_BUYER = "PlatformBuyer"
ROLE_FINANCE_ANALYST = "FinanceAnalyst"
ROLE_FINANCE_CONTROLLER = "FinanceController"

ROLES = {
    ROLE_RIGHTS_MANAGER,
    ROLE_PLATFORM_BUYER,
    ROLE_FINANCE_ANALYST,
    ROLE_FINANCE_CONTROLLER,
}


def get_caller():
    """Return (user_id, role); 401 when headers are missing or role unknown."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        err(ERR_UNAUTHENTICATED, "missing or unknown X-User-Role / X-User-ID headers")
    return user_id, role


def require_roles(*roles):
    """Authenticate, then authorize against the endpoint's role list."""
    user_id, role = get_caller()
    if role not in roles:
        err(ERR_FORBIDDEN, f"role {role} is not allowed on this endpoint")
    return user_id, role


def check_buyer_owns(user_id: str, role: str, platform_id):
    """PlatformBuyer ownership: X-User-ID must equal the resource's platform_id."""
    if role == ROLE_PLATFORM_BUYER and user_id != platform_id:
        err(ERR_FORBIDDEN, "PlatformBuyer may only act on its own platform's resources")
