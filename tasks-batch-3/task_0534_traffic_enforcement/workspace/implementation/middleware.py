from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_PORTAL_AUTH_FAILED
from db import db

KNOWN_ROLES = {
    "SystemAdmin",
    "ProgramAdmin",
    "ReviewOfficer",
    "Adjudicator",
    "RegisteredOwner",
    "Auditor",
}


def require_staff_auth(allowed_roles):
    """Validate X-User-ID + X-User-Role headers, then role permission.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED (missing/unknown role)
    then ERR_FORBIDDEN (role not permitted).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    if role not in allowed_roles:
        raise err(ERR_FORBIDDEN, "Role not permitted for this operation")
    return user_id, role


def require_portal_auth(body_or_args):
    """Authenticate an owner via registered_owner_id + portal_access_pin.

    Returns the owner record. Raises ERR_PORTAL_AUTH_FAILED on mismatch.
    """
    owner_id = body_or_args.get("registered_owner_id")
    pin = body_or_args.get("portal_access_pin")
    if not owner_id or not pin:
        raise err(ERR_PORTAL_AUTH_FAILED, "Missing portal credentials")
    owner = db.owners.get(owner_id)
    if owner is None or owner.get("portal_access_pin") != pin:
        raise err(ERR_PORTAL_AUTH_FAILED, "Invalid portal credentials")
    return owner
