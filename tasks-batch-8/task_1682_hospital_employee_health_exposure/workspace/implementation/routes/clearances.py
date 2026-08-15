"""Return-to-work clearances: list/read and physician decision."""
from flask import Blueprint

from db import now, serialize, store, touch
from errors import ApiError
from middleware import auth, body, check_enum, list_response, require_role
from response import success_list, success_object
from routes.common import get_or_404, staff_scope_check
from services.core import lift_restriction

bp = Blueprint("clearances", __name__)

DECISION_OUTCOMES = {"CLEARED", "DENIED"}

_READ_ROLES = {
    "EmployeeHealthNurse", "EmployeeHealthPhysician", "ComplianceOfficer",
    "SafetyOfficer", "StaffEmployee",
}


@bp.get("/employee-health/return-to-work-clearances")
def list_clearances():
    user_id, role = auth()
    require_role(role, _READ_ROLES)

    def scope(c):
        if role != "StaffEmployee":
            return True
        r = store.restrictions.get(c["restriction_id"])
        return r is not None and r["employee_id"] == user_id

    items, meta = list_response(
        store.clearances.values(),
        {
            "restriction_id": lambda c: c["restriction_id"],
            "status": lambda c: c["status"],
        },
        scope_fn=scope,
    )
    return success_list(items, meta)


@bp.get("/employee-health/return-to-work-clearances/<rid>")
def get_clearance(rid):
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    clearance = get_or_404(store.clearances, rid)
    if role == "StaffEmployee":
        r = store.restrictions.get(clearance["restriction_id"])
        staff_scope_check(role, user_id, r["employee_id"] if r else None)
    return success_object(serialize(clearance))


@bp.post("/employee-health/return-to-work-clearances/<rid>/decide")
def decide_clearance(rid):
    user_id, role = auth()
    require_role(role, {"EmployeeHealthPhysician"})
    clearance = get_or_404(store.clearances, rid)
    data = body()

    if clearance["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Clearance is not PENDING")
    restriction = store.restrictions.get(clearance["restriction_id"])
    if restriction is None or restriction["status"] != "ACTIVE":
        raise ApiError("ERR_RESTRICTION_NOT_ACTIVE", "Linked restriction is not ACTIVE")

    outcome = check_enum(data.get("outcome"), DECISION_OUTCOMES, "outcome")
    decision_note = data.get("decision_note")

    clearance["decided_by_user_id"] = user_id
    clearance["decided_at"] = now()
    clearance["decision_note"] = decision_note
    clearance["status"] = outcome
    touch(clearance)

    if outcome == "CLEARED":
        # CLEARED lifts the restriction; DENIED leaves it ACTIVE.
        lift_restriction(restriction, "LIFTED")
    return success_object(serialize(clearance))
