"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.8).

Headers (PRD §2.1):
  X-User-ID   — acting user id (opaque for Servicer; the Borrower/Merchant id
                for the entity-backed roles)
  X-User-Role — one of Servicer | Borrower | Merchant

Validation order is fixed (PRD §2.8): auth(401) -> authz(403) -> existence(404)
-> body schema(422) -> state/uniqueness/domain rules.
"""
from flask import request

from errors import err

VALID_ROLES = {"Servicer", "Borrower", "Merchant"}


def authenticate():
    """Validate the auth headers. Returns (user_id, role).

    A missing/unknown role, or a missing user id, yields ERR_UNAUTHENTICATED
    (PRD §2.1: both headers are mandatory; an unrecognized role is unauthenticated).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-Role header.")
    if not user_id or user_id.strip() == "":
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID header.")
    return user_id, role


def require_role(role, allowed):
    """ERR_FORBIDDEN if the caller's role is not permitted for the operation."""
    if role not in allowed:
        raise err(
            "ERR_FORBIDDEN",
            "Role '%s' is not permitted for this operation." % role,
        )


def require_borrower_owns(role, user_id, owner_borrower_id):
    """Entity-backed Borrower may only act on resources whose borrower FK is itself."""
    if role == "Borrower" and user_id != owner_borrower_id:
        raise err("ERR_FORBIDDEN", "Borrower does not own the targeted resource.")


def require_merchant_owns(role, user_id, owner_merchant_id):
    """Entity-backed Merchant may only act on resources whose merchant FK is itself."""
    if role == "Merchant" and user_id != owner_merchant_id:
        raise err("ERR_FORBIDDEN", "Merchant does not own the targeted resource.")
