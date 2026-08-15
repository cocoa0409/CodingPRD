"""Compliance holds: list/read plus explicit ComplianceOfficer release."""
from flask import Blueprint

from db import now, serialize, store, touch
from errors import ApiError
from middleware import auth, list_response, require_role
from response import success_list, success_object
from routes.common import get_or_404, staff_scope_check
from services.core import adjust_hold_count

bp = Blueprint("holds", __name__)

_READ_ROLES = {
    "EmployeeHealthNurse", "EmployeeHealthPhysician", "ComplianceOfficer",
    "SafetyOfficer", "StaffEmployee",
}


@bp.get("/employee-health/compliance-holds")
def list_holds():
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    scope = (lambda h: h["employee_id"] == user_id) if role == "StaffEmployee" else None
    items, meta = list_response(
        store.holds.values(),
        {
            "employee_id": lambda h: h["employee_id"],
            "cycle_id": lambda h: h["cycle_id"],
            "participation_id": lambda h: h["participation_id"],
            "status": lambda h: h["status"],
        },
        scope_fn=scope,
    )
    return success_list(items, meta)


@bp.get("/employee-health/compliance-holds/<rid>")
def get_hold(rid):
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    hold = get_or_404(store.holds, rid)
    staff_scope_check(role, user_id, hold["employee_id"])
    return success_object(serialize(hold))


@bp.post("/employee-health/compliance-holds/<rid>/release")
def release_hold(rid):
    user_id, role = auth()
    require_role(role, {"ComplianceOfficer"})
    hold = get_or_404(store.holds, rid)

    if hold["status"] != "ACTIVE":
        raise ApiError("ERR_HOLD_NOT_ACTIVE", "Hold is not ACTIVE")
    # Holds are released only after the underlying requirement is verified met.
    if hold["reason"] in ("TB_OVERDUE", "FIT_TEST_OVERDUE"):
        cycle = store.cycles.get(hold["cycle_id"])
        if cycle is None or cycle["status"] != "SATISFIED":
            raise ApiError(
                "ERR_UNDERLYING_REQUIREMENT_UNMET",
                "Linked cycle is not SATISFIED",
            )
    elif hold["reason"] == "CAMPAIGN_DELINQUENT":
        part = store.participations.get(hold["participation_id"])
        if part is None or part["status"] not in ("ADMINISTERED", "DECLINED", "EXEMPTED"):
            raise ApiError(
                "ERR_UNDERLYING_REQUIREMENT_UNMET",
                "Linked participation is not ADMINISTERED, DECLINED, or EXEMPTED",
            )

    hold["status"] = "RELEASED"
    hold["released_at"] = now()
    hold["released_by_user_id"] = user_id
    touch(hold)
    emp = store.employees[hold["employee_id"]]
    # Decrement; when the count reaches zero a SUSPENDED employee returns to ACTIVE.
    adjust_hold_count(emp, -1)
    return success_object(serialize(hold))
