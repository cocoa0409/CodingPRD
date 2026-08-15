"""Auth header extraction and role checking (PRD §2.1, §2.6)."""

from flask import request

from db import ROLES
from errors import ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE, raise_err


def authenticate():
    """Pipeline category 1: identity headers present, role declared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED,
                  "Missing or invalid X-User-ID / X-User-Role headers.")
    return uid, role


def require_role(role, allowed):
    """Pipeline category 2: role must be listed for the endpoint."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_ROLE,
                  "Role %s is not authorized for this endpoint." % role)


def forbid():
    raise_err(ERR_FORBIDDEN_ROLE,
              "AgencyCoordinator may only touch their own agency's resources.")
