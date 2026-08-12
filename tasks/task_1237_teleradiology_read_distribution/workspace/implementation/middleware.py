"""Auth header extraction, role recognition, and RBAC helpers.

Header names and role values per PRD §2.1:
  X-User-ID and X-User-Role on every request.
Roles: PlatformAdmin, DispatchOps, Radiologist, ClientHospitalUser, QaReviewer.
Entity-backed roles: Radiologist -> existing Radiologist row;
ClientHospitalUser -> existing ClientHospital row.
"""

from flask import request

from db import store
from errors import ApiError
import errors as E

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_DISPATCH_OPS = "DispatchOps"
ROLE_RADIOLOGIST = "Radiologist"
ROLE_CLIENT_HOSPITAL_USER = "ClientHospitalUser"
ROLE_QA_REVIEWER = "QaReviewer"

ALL_ROLES = {
    ROLE_PLATFORM_ADMIN,
    ROLE_DISPATCH_OPS,
    ROLE_RADIOLOGIST,
    ROLE_CLIENT_HOSPITAL_USER,
    ROLE_QA_REVIEWER,
}

ENTITY_BACKED = {
    ROLE_RADIOLOGIST: "radiologists",
    ROLE_CLIENT_HOSPITAL_USER: "hospitals",
}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    def __repr__(self):
        return f"<Principal {self.role}:{self.user_id}>"


def authenticate():
    """Priority-1 validation: headers present, role recognized, entity-backed
    role ids resolve to existing rows."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        E.raise_err(E.ERR_UNAUTHENTICATED, "Missing or unrecognized X-User-ID / X-User-Role headers")
    backing = ENTITY_BACKED.get(role)
    if backing is not None:
        if user_id not in getattr(store, backing):
            E.raise_err(E.ERR_UNAUTHENTICATED, f"{role} id does not resolve to an existing backing entity")
    return Principal(user_id, role)


def require_roles(principal, allowed):
    """Priority-2 validation: role listed for the endpoint."""
    if principal.role not in allowed:
        E.raise_err(E.ERR_UNAUTHORIZED, "Role not permitted on this endpoint")
