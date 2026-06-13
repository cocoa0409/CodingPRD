"""Auth header extraction and role checking (PRD §2.1, §2.8)."""
from flask import request, g
from errors import err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {"Subscriber", "CurationAdmin", "BillingOperator"}


def authenticate():
    """Validate the two mandatory auth headers (PRD §2.1). Priority 1."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unknown authentication headers.")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_roles(*allowed):
    """Authorize the acting role against the endpoint's permitted roles. Priority 2."""
    if g.role not in allowed:
        raise err(ERR_UNAUTHORIZED, "Role not permitted for this operation.")


def require_owner_subscriber(owner_subscriber_id):
    """Ownership check for entity-backed Subscriber role (PRD §2.1).

    Operator roles (CurationAdmin, BillingOperator) are scoped by capability,
    not ownership, so they pass. A Subscriber may act only on resources whose
    owning subscriber FK equals their own X-User-ID.
    """
    if g.role == "Subscriber" and g.user_id != owner_subscriber_id:
        raise err(ERR_UNAUTHORIZED, "Subscriber may act only on its own resources.")
