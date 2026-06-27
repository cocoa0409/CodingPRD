"""Auth header extraction and RBAC (PRD §2.1, §2.7, §4).

Headers (PRD §2.1):
  X-User-ID   — acting principal (Account.id when role is AccountHolder; opaque otherwise)
  X-User-Role — one of AccountHolder | ComplianceOfficer | ClearingSystem | MarketData
"""
from flask import request

import errors

ROLES = {"AccountHolder", "ComplianceOfficer", "ClearingSystem", "MarketData"}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if role missing/invalid."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or invalid X-User-Role")
    return user_id, role


def require_role(role, allowed):
    """ERR_FORBIDDEN if the authenticated role is not in the allowed set."""
    if role not in allowed:
        raise errors.err(errors.ERR_FORBIDDEN, "Role not permitted for this operation")


def require_account_owner(role, user_id, account_id):
    """For AccountHolder, enforce ownership: X-User-ID must equal the account id.
    Opaque operator roles are not subject to per-account ownership (PRD §2.1)."""
    if role == "AccountHolder" and user_id != account_id:
        raise errors.err(errors.ERR_FORBIDDEN, "AccountHolder does not own this account")
