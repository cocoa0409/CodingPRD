"""Auth header extraction and RBAC per PRD §2.1 / scaffold §1.7.

Headers (exact names from PRD §2.1): X-User-ID, X-User-Role.
Roles (exact spelling): ClaimsSupervisor, ClaimsAdjuster, TotalLossAdjuster,
SubrogationSpecialist.

Validation ordering (PRD §3.6): auth (401) -> role (403) -> existence (404)
-> request body (422) -> state -> OCC -> business gates.
"""
from flask import request

from errors import err

VALID_ROLES = {
    "ClaimsSupervisor",
    "ClaimsAdjuster",
    "TotalLossAdjuster",
    "SubrogationSpecialist",
}


class Principal(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate presence/well-formedness of the two mandatory headers.

    Both X-User-ID and X-User-Role must be present and non-empty, and the
    role must be one of the four recognized values. Otherwise
    ERR_UNAUTHENTICATED (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_UNAUTHENTICATED", "missing X-User-ID or X-User-Role")
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "":
        raise err("ERR_UNAUTHENTICATED", "empty X-User-ID or X-User-Role")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "unknown role: %s" % role)
    return Principal(user_id, role)


def authorize(principal, allowed_roles):
    """ERR_FORBIDDEN_ROLE (403) if the acting role is not in allowed_roles."""
    if principal.role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE",
                  "role %s may not perform this operation" % principal.role)
