"""Identity, role authorisation and exhibitor scoping (PRD 2.1, 2.7)."""
from flask import request

from db import db
from errors import ApiError

SHOW_DIRECTOR = "ShowDirector"
SALES_REP = "SalesRep"
FLOOR_MANAGER = "FloorManager"
EXHIBITOR = "Exhibitor"
REGISTRANT = "Registrant"

ROLES = (SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, EXHIBITOR, REGISTRANT)
ALL_ROLES = ROLES
READERS = (SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, EXHIBITOR)


class Ctx(object):
    def __init__(self, role, user_id, exhibitor):
        self.role = role
        self.user_id = user_id
        self.exhibitor = exhibitor

    @property
    def exhibitor_id(self):
        return self.exhibitor["id"] if self.exhibitor else None

    def enforce_scope(self, owner_exhibitor_id):
        """ERR_EXHIBITOR_SCOPE_VIOLATION when an exhibitor reaches outside itself."""
        if self.role != EXHIBITOR:
            return
        if owner_exhibitor_id is None:
            return
        if self.exhibitor_id != owner_exhibitor_id:
            raise ApiError("ERR_EXHIBITOR_SCOPE_VIOLATION",
                           "this exhibitor may only act on its own rows")

    def require_role(self, allowed):
        if self.role not in allowed:
            raise ApiError("ERR_ROLE_NOT_PERMITTED",
                           "role %s may not perform this operation" % self.role)


def authenticate(allowed_roles):
    role = request.headers.get("X-Role")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "a recognised X-Role header is required")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "role %s may not access this endpoint" % role)
    user_id = request.headers.get("X-User-ID")
    exhibitor = None
    if role == EXHIBITOR:
        role_id = request.headers.get("X-Role-Id")
        if not role_id or role_id not in db.exhibitors:
            raise ApiError("ERR_IDENTITY_REQUIRED",
                           "X-Role-Id must resolve to an existing exhibitor")
        exhibitor = db.exhibitors[role_id]
    return Ctx(role, user_id, exhibitor)
