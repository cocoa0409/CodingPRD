"""Auth header extraction + role authorization (PRD Section 2.1, 2.11)."""
from flask import request

from errors import err

VALID_ROLES = {"PlatformAdmin", "AccountHolder", "LocationOperator", "BillingAdmin"}


def get_auth():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if missing/malformed.

    Both X-User-ID and X-User-Role must be present and well-formed; the role
    must be one of the four recognized values (PRD 2.1).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-ID header.")
    if not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-Role header.")
    return user_id.strip(), role


def optional_auth():
    """Return (user_id, role) when valid headers are present, else (None, None).

    Used by the read-only catalog lookups (plans, locations, add-ons listing
    and fetching), which PRD 2.1 exempts from the authentication gate.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id and role in VALID_ROLES:
        return user_id.strip(), role
    return None, None


def require_roles(role, allowed):
    """Enforce that the role is permitted for this operation (PRD 2.1).

    PlatformAdmin is a superset operator (PRD 2.1) — wherever it is listed in
    the endpoint's authorized roles it passes; callers always include it where
    the spec grants it.
    """
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation.")


def require_owner(role, user_id, owning_account_id):
    """AccountHolder ownership check (PRD 2.1).

    An AccountHolder may only act on resources whose owning account id equals
    X-User-ID. Operator roles (PlatformAdmin, BillingAdmin, LocationOperator)
    are not entity-backed and skip ownership checks.
    """
    if role == "AccountHolder" and user_id != owning_account_id:
        raise err("ERR_FORBIDDEN", "Account holder does not own this resource.")
