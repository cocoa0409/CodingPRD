"""Auth header extraction and RBAC (PRD §2.1, SCAFFOLD §1.4 / §1.7).

Headers (authoritative per PRD §2.1):
  X-User-ID    -> acting user identifier
  X-User-Role  -> one of SalesAssociate, StoreManager, DeliveryDispatcher, Customer

Validation priority (PRD §2.9):
  auth(401) -> authorization(403) -> ownership(403) -> existence(404) -> shape(422) -> business
"""
from flask import request

from errors import err

KNOWN_ROLES = {"SalesAssociate", "StoreManager", "DeliveryDispatcher", "Customer"}


def get_auth():
    """Return (user_id, role) after validating presence and known role.

    Raises ERR_UNAUTHENTICATED (401) when X-User-ID or X-User-Role is missing,
    or X-User-Role is not a recognized role.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return user_id, role


def require_role(role, allowed):
    """Authorization gate. StoreManager inherits SalesAssociate + DeliveryDispatcher
    operations per PRD §2.1, so any operation listing either of those also admits
    StoreManager. We enforce by explicit allowed-set membership; callers include
    StoreManager in `allowed` wherever it is permitted.
    """
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED", "Role '%s' is not permitted for this operation." % role)
