from flask import request
import errors
from errors import err

RECOGNIZED_ROLES = {"ProgramAdmin", "Cardholder", "RewardsOps"}


def authenticate():
    """Validate auth headers (PRD §2.1, validation priority 1).

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED if either header is
    missing or the role is not recognized.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in RECOGNIZED_ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers.")
    return user_id, role


def require_role(role, allowed):
    """Validation priority 2: acting role permitted for this operation."""
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation.")


def require_owner(role, user_id, account_id):
    """Validation priority 3: Cardholder ownership check (PRD §2.1).

    Only applies when acting as Cardholder. Opaque roles (ProgramAdmin,
    RewardsOps) never undergo this check.
    """
    if role == "Cardholder" and account_id is not None and user_id != account_id:
        raise err(errors.ERR_NOT_ACCOUNT_OWNER, "Cardholder does not own this account.")
