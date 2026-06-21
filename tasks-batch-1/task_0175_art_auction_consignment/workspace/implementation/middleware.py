"""Auth header extraction, role checking, and request-body helpers.

Auth headers (PRD §2.1): X-User-ID and X-User-Role, both mandatory.
Recognized roles: SaleAdministrator, Auctioneer, FinanceOfficer, Seller,
Bidder, Viewer.
"""
from flask import request

import errors
from errors import err

RECOGNIZED_ROLES = {
    "SaleAdministrator",
    "Auctioneer",
    "FinanceOfficer",
    "Seller",
    "Bidder",
    "Viewer",
}

ENTITY_BACKED_ROLES = {"Seller", "Bidder"}


def get_identity():
    """Returns (user_id, role). Raises ERR_UNAUTHENTICATED when role missing
    or not recognized (PRD §2.1, validation priority 1)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in RECOGNIZED_ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or unrecognized X-User-Role")
    return user_id, role


def require_role(allowed_roles):
    """Authenticate then authorize. Returns (user_id, role).

    Priority 1: ERR_UNAUTHENTICATED (missing/unknown role).
    Priority 2: ERR_FORBIDDEN_ROLE (role not permitted for this op).
    """
    user_id, role = get_identity()
    if role not in allowed_roles:
        raise err(errors.ERR_FORBIDDEN_ROLE,
                  "Role %s is not permitted for this operation" % role)
    return user_id, role


def get_json_body():
    """Parse the request body as JSON. A non-JSON / unparseable body for a
    write endpoint is treated as a malformed request."""
    if request.method in ("POST", "PATCH", "PUT"):
        data = request.get_json(silent=True)
        if data is None:
            # Empty body is acceptable for transition endpoints that take no
            # input; represent it as an empty object so callers can read keys.
            if request.data and request.data.strip():
                raise err(errors.ERR_INVALID_REQUEST, "Malformed JSON body")
            return {}
        if not isinstance(data, dict):
            raise err(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
        return data
    return {}
