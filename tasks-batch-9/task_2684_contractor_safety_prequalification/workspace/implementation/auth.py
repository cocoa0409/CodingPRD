"""Header authentication, role authorization and ownership narrowing (PRD 2.1)."""
from flask import request

import store
from errors import fail

ROLE_NETWORK_ADMIN = "NetworkAdmin"
ROLE_CONTRACTOR_ADMIN = "ContractorAdmin"
ROLE_CLIENT_SAFETY_MANAGER = "ClientSafetyManager"
ROLE_VERIFICATION_ANALYST = "VerificationAnalyst"

ALL_ROLES = [
    ROLE_NETWORK_ADMIN,
    ROLE_CONTRACTOR_ADMIN,
    ROLE_CLIENT_SAFETY_MANAGER,
    ROLE_VERIFICATION_ANALYST,
]

READ_ROLES = [
    ROLE_NETWORK_ADMIN,
    ROLE_CLIENT_SAFETY_MANAGER,
    ROLE_VERIFICATION_ANALYST,
    ROLE_CONTRACTOR_ADMIN,
]


def authenticate(allowed_roles):
    """Priority 1 (ERR_UNAUTHENTICATED) then priority 2 (ERR_FORBIDDEN_ROLE)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a declared role.")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % role)
    return user_id, role


def check_owner(role, user_id, contractor_id=None, client_id=None):
    """Priority 7 -- entity_backed roles must act inside their own subtree."""
    if role == ROLE_CONTRACTOR_ADMIN and contractor_id is not None:
        if user_id != contractor_id:
            fail("ERR_NOT_RESOURCE_OWNER", "Acting contractor does not own this resource.")
    if role == ROLE_CLIENT_SAFETY_MANAGER and client_id is not None:
        if user_id != client_id:
            fail("ERR_NOT_RESOURCE_OWNER", "Acting client does not own this resource.")


def check_owner_any_contractor(role, user_id, contractor_ids, client_id=None):
    """Ownership where several contractor references make the row reachable."""
    if role == ROLE_CONTRACTOR_ADMIN:
        if user_id not in [c for c in contractor_ids if c is not None]:
            fail("ERR_NOT_RESOURCE_OWNER", "Acting contractor does not own this resource.")
    if role == ROLE_CLIENT_SAFETY_MANAGER and client_id is not None:
        if user_id != client_id:
            fail("ERR_NOT_RESOURCE_OWNER", "Acting client does not own this resource.")


def visible(role, user_id, contractor_id=None, client_id=None):
    """Read narrowing for list endpoints."""
    if role == ROLE_CONTRACTOR_ADMIN and contractor_id is not None:
        return user_id == contractor_id
    if role == ROLE_CLIENT_SAFETY_MANAGER and client_id is not None:
        return user_id == client_id
    return True


def visible_any_contractor(role, user_id, contractor_ids, client_id=None):
    if role == ROLE_CONTRACTOR_ADMIN:
        ids = [c for c in contractor_ids if c is not None]
        if ids:
            return user_id in ids
        return True
    if role == ROLE_CLIENT_SAFETY_MANAGER and client_id is not None:
        return user_id == client_id
    return True
