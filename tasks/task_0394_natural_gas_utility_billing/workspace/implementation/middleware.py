"""Auth header extraction and role checking (PRD §2.1, §2.10).

Headers (authoritative names from PRD §2.1):
    X-User-ID   — calling principal identifier
    X-User-Role — one of BillingAdmin | CustomerService | FieldTech | Account

- Missing/invalid role  -> ERR_UNAUTHENTICATED (401)
- Recognized but not permitted (incl. Account reaching outside its own
  account)                -> ERR_FORBIDDEN (403)
"""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, err

VALID_ROLES = {"BillingAdmin", "CustomerService", "FieldTech", "Account"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate X-User-Role. Returns a Principal or raises ERR_UNAUTHENTICATED."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-Role header")
    return Principal(user_id, role)


def require_role(principal, allowed_roles):
    """Raise ERR_FORBIDDEN unless the principal's role is in allowed_roles."""
    if principal.role not in allowed_roles:
        raise err(ERR_FORBIDDEN, "Role not permitted for this operation")


def require_account_ownership(principal, account_id):
    """For an Account principal, enforce that it acts only on its own account.

    PRD §2.1: ownership checks compare the resource's account_id to X-User-ID.
    Opaque roles (BillingAdmin/CustomerService/FieldTech) are never ownership
    checked.
    """
    if principal.role == "Account":
        if principal.user_id != account_id:
            raise err(ERR_FORBIDDEN, "Account principal may only act on its own account")
