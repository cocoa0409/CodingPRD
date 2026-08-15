"""Pre-placement screenings: create-with-supersede (OCC), components, decide."""
from flask import Blueprint

from db import base_fields, now, serialize, store, touch
from errors import ApiError
from middleware import auth, body, check_enum, list_response, require_role
from response import success_list, success_object
from routes.common import get_or_404, staff_scope_check
from services.calculations import REQUIRED_TITER_DISEASES, latest_titer
from util import parse_dt

bp = Blueprint("screenings", __name__)

COMPONENTS = {"PHYSICAL", "TB_BASELINE", "MED_EVAL"}
COMPONENT_FIELD = {
    "PHYSICAL": "physical_completed_at",
    "TB_BASELINE": "tb_baseline_completed_at",
    "MED_EVAL": "med_eval_completed_at",
}

_READ_ROLES = {
    "EmployeeHealthNurse", "EmployeeHealthPhysician", "ComplianceOfficer",
    "SafetyOfficer", "StaffEmployee",
}


def _scope(role, user_id):
    if role == "StaffEmployee":
        return lambda s: s["employee_id"] == user_id
    return None


@bp.post("/employee-health/employees/<emp_id>/pre-placement-screenings")
def create_screening(emp_id):
    user_id, role = auth()
    require_role(role, {"EmployeeHealthNurse"})
    emp = get_or_404(store.employees, emp_id)
    data = body()

    # OCC (priority 3.5 / PRD 2.7): stale employee version rejected before any
    # business check; evaluated only when the field is present and well-formed.
    expected = data.get("expected_employee_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != emp["version"]:
            raise ApiError(
                "ERR_STALE_EMPLOYEE_VERSION",
                "expected_employee_version does not match the employee's current version",
            )
    elif expected is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: expected_employee_version")
    else:
        raise ApiError(
            "ERR_INVALID_REQUEST", "expected_employee_version must be an integer"
        )

    # Create-with-supersede: any existing IN_PROGRESS screening becomes VOID.
    for s in store.screenings.values():
        if s["employee_id"] == emp["id"] and s["status"] == "IN_PROGRESS":
            s["status"] = "VOID"
            touch(s)

    screening = base_fields()
    screening.update(
        {
            "employee_id": emp["id"],
            "status": "IN_PROGRESS",
            "physical_completed_at": None,
            "tb_baseline_completed_at": None,
            "med_eval_completed_at": None,
            "decided_by_user_id": None,
            "decided_at": None,
        }
    )
    store.screenings[screening["id"]] = screening
    # Opening a screening mutates the employee (supersession anchor).
    touch(emp)
    return success_object(serialize(screening), status=201)


@bp.get("/employee-health/pre-placement-screenings")
def list_screenings():
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    items, meta = list_response(
        store.screenings.values(),
        {
            "employee_id": lambda s: s["employee_id"],
            "status": lambda s: s["status"],
        },
        scope_fn=_scope(role, user_id),
    )
    return success_list(items, meta)


@bp.get("/employee-health/pre-placement-screenings/<rid>")
def get_screening(rid):
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    screening = get_or_404(store.screenings, rid)
    staff_scope_check(role, user_id, screening["employee_id"])
    return success_object(serialize(screening))


@bp.post("/employee-health/pre-placement-screenings/<rid>/components/complete")
def complete_component(rid):
    user_id, role = auth()
    require_role(role, {"EmployeeHealthNurse"})
    screening = get_or_404(store.screenings, rid)
    data = body()

    component = data.get("component")
    # State legality: screening must be IN_PROGRESS; each component completable once.
    if screening["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Screening is not IN_PROGRESS")
    if component in COMPONENT_FIELD and screening[COMPONENT_FIELD[component]] is not None:
        raise ApiError("ERR_INVALID_STATE", "Component %s is already completed" % component)

    # Temporal: completed_at must not lie in the future.
    completed_at = parse_dt(data.get("completed_at"))
    if completed_at is not None and completed_at > now():
        raise ApiError("ERR_COMPLETION_OUT_OF_RANGE", "completed_at must not be in the future")

    # Field shape.
    check_enum(component, COMPONENTS, "component")
    if completed_at is None:
        raise ApiError("ERR_INVALID_REQUEST", "completed_at must be a valid ISO 8601 timestamp")

    screening[COMPONENT_FIELD[component]] = completed_at
    touch(screening)
    return success_object(serialize(screening))


@bp.post("/employee-health/pre-placement-screenings/<rid>/decide")
def decide_screening(rid):
    user_id, role = auth()
    require_role(role, {"EmployeeHealthPhysician"})
    screening = get_or_404(store.screenings, rid)
    data = body()
    outcome = data.get("outcome")

    if screening["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Screening is not IN_PROGRESS")

    emp = store.employees[screening["employee_id"]]
    if outcome == "CLEARED":
        # Safety gates: components first, then immunity.
        missing = (
            screening["physical_completed_at"] is None
            or screening["tb_baseline_completed_at"] is None
            or (emp["requires_respirator"] and screening["med_eval_completed_at"] is None)
        )
        if missing:
            raise ApiError(
                "ERR_COMPONENT_INCOMPLETE",
                "Required screening components are not completed",
            )
        for disease in REQUIRED_TITER_DISEASES:
            latest = latest_titer(emp["id"], disease)
            if latest is None or latest["immunity_status"] != "IMMUNE":
                raise ApiError(
                    "ERR_IMMUNITY_NOT_ESTABLISHED",
                    "Latest titer for %s is not IMMUNE" % disease,
                )
    elif outcome != "FAILED":
        raise ApiError("ERR_INVALID_ENUM", "outcome must be one of ['CLEARED', 'FAILED']")

    screening["decided_by_user_id"] = user_id
    screening["decided_at"] = now()
    screening["status"] = outcome
    touch(screening)
    if outcome == "CLEARED" and emp["status"] == "PREPLACEMENT":
        emp["status"] = "ACTIVE"
        touch(emp)
    return success_object(serialize(screening))
