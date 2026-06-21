"""Auth header extraction and RBAC enforcement (PRD §2.1, §1.7).

Auth headers (PRD §2.1):
  X-User-ID    — opaque acting-user identifier
  X-User-Role  — one of the six recognized roles

Roles (PRD §2.1), spelled precisely:
  PlatformAdmin, ClauseLibrarian, ContractManager, ContractApprover,
  RiskOfficer, Signer
"""

from functools import wraps

from flask import g, request

from errors import unauthenticated, unauthorized

KNOWN_ROLES = {
    "PlatformAdmin",
    "ClauseLibrarian",
    "ContractManager",
    "ContractApprover",
    "RiskOfficer",
    "Signer",
}


def authenticate():
    """Validate the two mandatory headers. Returns (user_id, role).

    Raises ERR_UNAUTHENTICATED if either header is missing, or if X-User-Role
    is not a recognized role (PRD §2.1, §1.4 priority 1).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise unauthenticated("Missing X-User-ID or X-User-Role header.")
    if role not in KNOWN_ROLES:
        raise unauthenticated("Unknown role: %s" % role)
    return user_id, role


def require_roles(*allowed_roles):
    """Decorator: authenticate, then enforce that the acting role is allowed.

    Priority 1 (auth presence) is checked before priority 2 (authorization),
    matching §1.4. The acting user_id and role are stashed on flask.g.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            g.user_id = user_id
            g.role = role
            if role not in allowed_roles:
                raise unauthorized("Role %s may not call this endpoint." % role)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
