"""Auth header extraction and role checks (PRD 2.1; validation priorities 1-2).

Every request must carry X-User-ID and X-User-Role.  A missing header, or a
role value outside the declared set, yields ERR_UNAUTHENTICATED (401).  A
declared role that is not listed for the endpoint yields ERR_FORBIDDEN_ROLE
(403).  For the Distributor role, X-User-ID is the id of the acting
Distributor entity; for every other role it is an opaque operator identifier.
"""

from flask import request

from errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_UNAUTHENTICATED,
    raise_error,
)

ALL_ROLES = {
    "PlantAdmin",
    "CoreInspector",
    "ShopTechnician",
    "QualityInspector",
    "Distributor",
    "WarrantyAdjuster",
}

ALL_READ_ROLES = sorted(ALL_ROLES)


class Caller(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_caller():
    """Priority 1: header presence and declared role."""
    user_id = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(
            ERR_UNAUTHENTICATED,
            "X-User-ID and X-User-Role headers must both be present and "
            "X-User-Role must be a declared role.",
        )
    return Caller(user_id, role)


def check_role_allowed(caller, allowed_roles):
    """Priority 2: caller role must be listed in the endpoint's roles."""
    if caller.role not in allowed_roles:
        raise_error(
            ERR_FORBIDDEN_ROLE,
            "role %s is not authorized for this endpoint" % caller.role,
        )


def authorized(allowed_roles):
    caller = get_caller()
    check_role_allowed(caller, allowed_roles)
    return caller
