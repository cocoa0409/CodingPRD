from flask import Blueprint, request

from db import store, base_record, touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_REST_NOT_SATISFIED,
    ERR_DUPLICATE,
)
from middleware import auth, require_roles, require_owner
from response import ok_obj, paged
from services import (
    CRAFTS,
    MIN_UNDISTURBED_REST_MINUTES,
    freeze_employee_slots,
    restore_employee_slots,
    vacate_employee_slots,
    return_to_board_tail,
    open_rest_for,
    rest_elapsed,
)
from validators import body, req_str, req_enum, req_dt

bp = Blueprint("employees", __name__)


def _get_employee(emp_id):
    emp = store.employees.get(emp_id)
    if emp is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Employee '%s' not found." % emp_id)
    return emp


@bp.post("/api/employees")
def create_employee():
    data = body()
    employee_number = req_str(data, "employee_number")
    full_name = req_str(data, "full_name")
    craft = req_enum(data, "craft", CRAFTS)
    seniority_date = req_dt(data, "seniority_date")
    home_terminal = req_str(data, "home_terminal")
    _, role = auth()
    require_roles(role, ("CrewManager",))
    if any(e["employee_number"] == employee_number for e in store.employees.values()):
        raise ApiError(ERR_DUPLICATE, 409, "employee_number already exists.")
    rec = base_record()
    rec.update({
        "employee_number": employee_number,
        "full_name": full_name,
        "craft": craft,
        "seniority_date": seniority_date,
        "availability_status": "AVAILABLE",
        "cumulative_duty_minutes_month": 0,
        "fatigue_score": 0.0,
        "home_terminal": home_terminal,
    })
    store.employees[rec["id"]] = rec
    return ok_obj(rec, 201)


@bp.get("/api/employees")
def list_employees():
    _, role = auth()
    require_roles(role, ("CrewManager", "CrewCaller"))
    rows = list(store.employees.values())
    craft = request.args.get("craft")
    if craft is not None:
        rows = [r for r in rows if r["craft"] == craft]
    av = request.args.get("availability_status")
    if av is not None:
        rows = [r for r in rows if r["availability_status"] == av]
    return paged(rows, request.args)


@bp.get("/api/employees/<emp_id>")
def get_employee(emp_id):
    _, role = auth()
    require_roles(role, ("CrewManager", "CrewCaller", "Employee"))
    return ok_obj(_get_employee(emp_id))


@bp.post("/api/employees/<emp_id>/lay-off")
def lay_off(emp_id):
    uid, role = auth()
    require_roles(role, ("Employee",))
    require_owner(uid, emp_id)
    emp = _get_employee(emp_id)
    if emp["availability_status"] != "AVAILABLE":
        raise ApiError(ERR_INVALID_STATE, 409, "Employee is not AVAILABLE.")
    freeze_employee_slots(emp_id)
    emp["availability_status"] = "MARKED_OFF"
    touch(emp)
    return ok_obj(emp)


@bp.post("/api/employees/<emp_id>/mark-up")
def mark_up(emp_id):
    uid, role = auth()
    require_roles(role, ("Employee",))
    require_owner(uid, emp_id)
    emp = _get_employee(emp_id)
    if emp["availability_status"] not in ("MARKED_OFF", "ON_REST"):
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Employee must be MARKED_OFF or ON_REST to mark up.",
        )
    rp = open_rest_for(emp_id)
    if rp is not None and rest_elapsed(rp) < MIN_UNDISTURBED_REST_MINUTES:
        raise ApiError(
            ERR_REST_NOT_SATISFIED, 422,
            "Open rest period has not reached the 600-minute undisturbed minimum.",
        )
    if rp is not None:
        elapsed = rest_elapsed(rp)
        rp["rest_end"] = store.now
        rp["undisturbed_minutes"] = elapsed
        rp["rest_status"] = (
            "SATISFIED" if elapsed >= MIN_UNDISTURBED_REST_MINUTES else "DISTURBED"
        )
    if emp["availability_status"] == "MARKED_OFF":
        restore_employee_slots(emp_id)
    emp["availability_status"] = "AVAILABLE"
    touch(emp)
    return ok_obj(emp)


@bp.post("/api/employees/<emp_id>/return-from-leave")
def return_from_leave(emp_id):
    uid, role = auth()
    require_roles(role, ("Employee",))
    require_owner(uid, emp_id)
    emp = _get_employee(emp_id)
    if emp["availability_status"] != "ON_LEAVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Employee is not ON_LEAVE.")
    emp["availability_status"] = "AVAILABLE"
    touch(emp)
    return_to_board_tail(emp)
    return ok_obj(emp)


@bp.post("/api/employees/<emp_id>/suspend")
def suspend(emp_id):
    _, role = auth()
    require_roles(role, ("CrewManager",))
    emp = _get_employee(emp_id)
    if emp["availability_status"] != "AVAILABLE":
        raise ApiError(ERR_INVALID_STATE, 409, "Employee is not AVAILABLE.")
    vacate_employee_slots(emp_id)
    for c in store.calls.values():
        if c["employee_id"] == emp_id and c["call_status"] == "OFFERED":
            c["call_status"] = "RESCINDED"
            c["responded_at"] = store.now
            touch(c)
    emp["availability_status"] = "SUSPENDED"
    touch(emp)
    return ok_obj(emp)


@bp.post("/api/employees/<emp_id>/reinstate")
def reinstate(emp_id):
    _, role = auth()
    require_roles(role, ("CrewManager",))
    emp = _get_employee(emp_id)
    if emp["availability_status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Employee is not SUSPENDED.")
    emp["availability_status"] = "AVAILABLE"
    touch(emp)
    return_to_board_tail(emp)
    return ok_obj(emp)
