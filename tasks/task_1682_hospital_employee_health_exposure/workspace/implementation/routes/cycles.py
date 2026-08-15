"""Annual requirement cycles: open (ComplianceOfficer), completions (Nurse)."""
from flask import Blueprint

from db import base_fields, now, serialize, store, touch
from errors import ApiError
from middleware import auth, body, check_enum, list_response, require_role
from response import success_list, success_object
from routes.common import get_or_404, staff_scope_check
from services.calculations import compute_cycle_due_dates, cycle_is_satisfied
from util import parse_dt

bp = Blueprint("cycles", __name__)

CYCLE_MODES = {"CALENDAR_YEAR", "ROLLING_ANNIVERSARY"}
REQUIREMENT_TYPES = {"TB_SCREENING", "FIT_TEST"}
REQUIREMENT_FIELD = {"TB_SCREENING": "tb_completed_at", "FIT_TEST": "fit_test_completed_at"}

_READ_ROLES = {
    "EmployeeHealthNurse", "EmployeeHealthPhysician", "ComplianceOfficer",
    "SafetyOfficer", "StaffEmployee",
}


@bp.post("/employee-health/employees/<emp_id>/annual-requirement-cycles")
def create_cycle(emp_id):
    user_id, role = auth()
    require_role(role, {"ComplianceOfficer"})
    emp = get_or_404(store.employees, emp_id)
    data = body()

    # State family (priority 6) precedes the safety gate (priority 7).
    if any(
        c["employee_id"] == emp["id"] and c["status"] in ("OPEN", "OVERDUE")
        for c in store.cycles.values()
    ):
        raise ApiError(
            "ERR_CYCLE_ALREADY_OPEN",
            "Employee already has a cycle in OPEN or OVERDUE",
        )
    if emp["status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYEE_NOT_ACTIVE", "Employee must be ACTIVE to open a cycle")

    # Field shape.
    cycle_year = data.get("cycle_year")
    if not isinstance(cycle_year, int) or isinstance(cycle_year, bool):
        raise ApiError("ERR_INVALID_REQUEST", "cycle_year must be an integer")
    cycle_mode = check_enum(data.get("cycle_mode"), CYCLE_MODES, "cycle_mode")

    tb_due, fit_due = compute_cycle_due_dates(emp, cycle_year, cycle_mode)

    cycle = base_fields()
    cycle.update(
        {
            "employee_id": emp["id"],
            "cycle_year": cycle_year,
            "cycle_mode": cycle_mode,
            "tb_due_date": tb_due,
            "fit_test_due_date": fit_due,
            "tb_completed_at": None,
            "fit_test_completed_at": None,
            "status": "OPEN",
        }
    )
    store.cycles[cycle["id"]] = cycle
    return success_object(serialize(cycle), status=201)


@bp.get("/employee-health/annual-requirement-cycles")
def list_cycles():
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    scope = (lambda c: c["employee_id"] == user_id) if role == "StaffEmployee" else None
    items, meta = list_response(
        store.cycles.values(),
        {
            "employee_id": lambda c: c["employee_id"],
            "status": lambda c: c["status"],
        },
        scope_fn=scope,
    )
    return success_list(items, meta)


@bp.get("/employee-health/annual-requirement-cycles/<rid>")
def get_cycle(rid):
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    cycle = get_or_404(store.cycles, rid)
    staff_scope_check(role, user_id, cycle["employee_id"])
    return success_object(serialize(cycle))


@bp.post("/employee-health/annual-requirement-cycles/<rid>/completions")
def record_completion(rid):
    user_id, role = auth()
    require_role(role, {"EmployeeHealthNurse"})
    cycle = get_or_404(store.cycles, rid)
    data = body()

    requirement_type = data.get("requirement_type")
    emp = store.employees[cycle["employee_id"]]

    # State legality: each requirement completable once per cycle.
    if requirement_type in REQUIREMENT_FIELD:
        if cycle[REQUIREMENT_FIELD[requirement_type]] is not None:
            raise ApiError(
                "ERR_INVALID_STATE",
                "Requirement %s is already completed for this cycle" % requirement_type,
            )

    # Safety gate: fit test only when the employee requires a respirator.
    if requirement_type == "FIT_TEST" and not emp["requires_respirator"]:
        raise ApiError(
            "ERR_FIT_TEST_NOT_REQUIRED",
            "Employee does not require respirator fit testing",
        )

    # Temporal: not in the future and not before the cycle's creation.
    completed_at = parse_dt(data.get("completed_at"))
    if completed_at is not None and (
        completed_at > now() or completed_at < cycle["created_at"]
    ):
        raise ApiError(
            "ERR_COMPLETION_OUT_OF_RANGE",
            "completed_at must not be in the future or precede the cycle's creation",
        )

    # Field shape.
    check_enum(requirement_type, REQUIREMENT_TYPES, "requirement_type")
    if completed_at is None:
        raise ApiError("ERR_INVALID_REQUEST", "completed_at must be a valid ISO 8601 timestamp")

    cycle[REQUIREMENT_FIELD[requirement_type]] = completed_at
    # Satisfaction is re-evaluated after every completions call (late completion
    # allowed: OPEN or OVERDUE both move to SATISFIED); one mutation, one version bump.
    if cycle["status"] in ("OPEN", "OVERDUE") and cycle_is_satisfied(cycle, emp):
        cycle["status"] = "SATISFIED"
    touch(cycle)
    return success_object(serialize(cycle))
