"""Auth header extraction and RBAC enforcement (PRD §2.1)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

VALID_ROLES = {"Anonymous", "Member", "Bookseller", "InventoryManager", "StoreAdmin"}


def get_auth():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if headers missing/malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def authorize(allowed_roles, anonymous_ok=False):
    """Authenticate then check role permission.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED (401) or ERR_FORBIDDEN (403).
    `allowed_roles` is the set/list of roles permitted for this operation.
    """
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise err(ERR_FORBIDDEN, f"Role {role} is not permitted for this operation")
    return user_id, role


def check_owner(user_id, role, owner_member_id):
    """For a Member acting on a member-scoped resource, enforce that the resource's
    owning member_id equals X-User-ID (PRD §2.1). Other roles bypass the check.
    Priority: ownership (403) is checked AFTER role permission, BEFORE existence —
    but the owning id must already be known, so callers run this after fetching.
    """
    from errors import ERR_NOT_RESOURCE_OWNER
    if role == "Member" and owner_member_id != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Member does not own this resource")
