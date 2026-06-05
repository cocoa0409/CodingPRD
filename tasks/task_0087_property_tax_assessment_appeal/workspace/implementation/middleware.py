"""Auth header extraction and RBAC (PRD §2.1).

Headers: X-User-ID and X-User-Role.
Valid roles (exactly five): Assessor, Reviewer, HearingOfficer, Taxpayer, Anonymous.
Missing/unrecognized on a protected endpoint -> ERR_UNAUTHENTICATED (401).
Authenticated but role not permitted -> ERR_UNAUTHORIZED (403).
"""
from flask import request

from errors import err

VALID_ROLES = {"Assessor", "Reviewer", "HearingOfficer", "Taxpayer", "Anonymous"}


def get_identity():
    """Return (user_id, role) from headers, both possibly None/invalid."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def require_auth():
    """Validate presence + recognition of the two headers.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED when either header is
    missing or the role is not one of the five recognised values.
    """
    user_id, role = get_identity()
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, role


def require_roles(allowed):
    """Authenticate, then enforce role authorization (§2.1, §2.8).

    `allowed` is the list of permitted role names for the endpoint.
    Returns (user_id, role).
    """
    user_id, role = require_auth()
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation")
    return user_id, role
