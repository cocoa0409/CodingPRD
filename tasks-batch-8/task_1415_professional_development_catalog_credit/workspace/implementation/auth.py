"""Auth context: X-User-ID / X-User-Role headers, role gating, kind checks."""
from flask import request

from db import store
from errors import err, ERR_MISSING_CONTEXT, ERR_FORBIDDEN_ROLE

ROLES = ("Teacher", "BuildingAdmin", "Instructor", "PDCoordinator",
         "BusinessOfficer", "Auditor")
ENTITY_BACKED = ("Teacher", "BuildingAdmin", "Instructor")


class Ctx:
    def __init__(self, user_id, role, employee):
        self.user_id = user_id
        self.role = role
        self.employee = employee  # Employee row for entity-backed roles


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise err(ERR_MISSING_CONTEXT,
                  "X-User-ID and X-User-Role headers are required and role must be declared")
    return uid, role


def require_role(*allowed):
    """Ladder steps 1-2: headers/declared role, then endpoint permission and
    the entity-backed kind check (Teacher -> TEACHER, BuildingAdmin -> ADMIN;
    Instructor -> must be an existing Employee)."""
    uid, role = authenticate()
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "role %s is not permitted on this endpoint" % role)
    emp = None
    if role in ENTITY_BACKED:
        emp = store.employees.get(uid)
        if emp is None:
            raise err(ERR_FORBIDDEN_ROLE, "entity-backed role requires an existing employee")
        if role == "Teacher" and emp["employee_kind"] != "TEACHER":
            raise err(ERR_FORBIDDEN_ROLE, "Teacher role requires employee_kind TEACHER")
        if role == "BuildingAdmin" and emp["employee_kind"] != "ADMIN":
            raise err(ERR_FORBIDDEN_ROLE, "BuildingAdmin role requires employee_kind ADMIN")
    return Ctx(uid, role, emp)


def require_any_role():
    return require_role(*ROLES)
