"""Auth header extraction and RBAC (PRD §2.1).

Headers (PRD §2.1):
  X-User-ID   — acting principal. For TaxPreparer this is the acting Preparer.id
                (entity-backed); for the other three roles it is an opaque
                operator identifier, recorded but never matched to an entity id.
  X-User-Role — one of OfficeManager | FrontDeskAgent | TaxPreparer | BankProductOfficer

Precedence (PRD §2.1, §2.5): authentication (401) before permission (403) before
any resource lookup (404)."""
from flask import request

import errors

ROLES = {"OfficeManager", "FrontDeskAgent", "TaxPreparer", "BankProductOfficer"}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if either header is
    missing or X-User-Role is not a known role."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or unknown X-User-Role")
    if user_id is None or user_id == "":
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing X-User-ID")
    return user_id, role


def require_role(role, allowed):
    """ERR_FORBIDDEN if the authenticated role is not in the allowed set."""
    if role not in allowed:
        raise errors.err(errors.ERR_FORBIDDEN, "Role not permitted for this operation")
