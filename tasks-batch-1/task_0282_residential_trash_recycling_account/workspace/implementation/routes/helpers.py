"""Per-request gate: authenticate then authorize the role for the endpoint."""
from errors import err
from middleware import authenticate, authorize


def gate(allowed_roles):
    """Run auth (priority 1) then RBAC (priority 2). Returns (user_id, role)."""
    user_id, role = authenticate()
    authorize(role, allowed_roles)
    return user_id, role


def require_ownership(role, user_id, account_id):
    """PRD §2.1: when the actor is an AccountHolder, any resource that references
    a ServiceAccount must belong to that holder (account FK == X-User-ID).
    Dispatcher and CrewLead are opaque principals and bypass this check.
    """
    if role == "AccountHolder" and account_id != user_id:
        raise err("ERR_FORBIDDEN", "AccountHolder may only access its own resources.")
