"""Authentication, role gating and the two entity-backed read scopes."""

from flask import request

from errors import ApiError
from store import db

ALL_ROLES = (
    "PayrollAdmin",
    "PayrollPreparer",
    "ComplianceOfficer",
    "ShiftManager",
    "Employee",
)

OPERATOR_ROLES = ("PayrollAdmin", "PayrollPreparer", "ComplianceOfficer")


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_employee(self):
        return self.role == "Employee"

    @property
    def is_manager(self):
        return self.role == "ShiftManager"

    @property
    def is_operator(self):
        return self.role in OPERATOR_ROLES

    def employee_row(self):
        """The Employee row named by X-User-ID for the entity-backed roles."""
        return db.employees.get(self.user_id)

    def scope_location_id(self):
        row = self.employee_row()
        return row["location_id"] if row else None


def authorize(roles):
    """Rung 1 then rung 2: headers present, then role authorised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return Actor(user_id, role)


def not_owner():
    return ApiError("ERR_NOT_RESOURCE_OWNER")


# ---------------------------------------------------------------------------
# single-resource ownership (rung 6)
# ---------------------------------------------------------------------------

def check_employee_scope(actor, employee_id):
    """Confine an Employee to its own rows and a ShiftManager to its unit."""
    if actor.is_employee:
        if employee_id != actor.user_id:
            raise not_owner()
        return
    if actor.is_manager:
        unit = actor.scope_location_id()
        target = db.employees.get(employee_id)
        if unit is None or target is None or target["location_id"] != unit:
            raise not_owner()


def check_shift_scope(actor, shift):
    if actor.is_employee:
        if shift["employee_id"] != actor.user_id:
            raise not_owner()
        return
    if actor.is_manager:
        unit = actor.scope_location_id()
        if unit is None or shift["location_id"] != unit:
            raise not_owner()


# ---------------------------------------------------------------------------
# collection scoping (2.11)
# ---------------------------------------------------------------------------

def scope_rows_by_employee(actor, rows, key="employee_id"):
    """Narrow a collection for the two entity-backed roles."""
    if actor.is_employee:
        return [r for r in rows if r.get(key) == actor.user_id]
    if actor.is_manager:
        unit = actor.scope_location_id()
        if unit is None:
            return []
        out = []
        for row in rows:
            emp = db.employees.get(row.get(key))
            if emp is not None and emp["location_id"] == unit:
                out.append(row)
        return out
    return rows


def scope_shifts(actor, rows):
    if actor.is_employee:
        return [r for r in rows if r.get("employee_id") == actor.user_id]
    if actor.is_manager:
        unit = actor.scope_location_id()
        if unit is None:
            return []
        return [r for r in rows if r.get("location_id") == unit]
    return rows


def scope_disputes(actor, rows):
    """A ShiftManager sees only its own unit's disputes."""
    if actor.is_manager:
        return scope_rows_by_employee(actor, rows, "raised_by_employee_id")
    return rows
