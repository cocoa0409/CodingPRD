"""Patients (census: admit / transfer / discharge) and Employees."""
from flask import Blueprint, request

import db
from errors import (
    ERR_DUPLICATE_MRN,
    ERR_INVALID_REQUEST,
    ERR_PATIENT_NOT_ADMITTED,
    ERR_PATIENT_NOT_FOUND,
    ERR_EMPLOYEE_NOT_FOUND,
    ERR_UNIT_NOT_FOUND,
    raise_err,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.core import new_entity, touch
from services.serializers import employee_view, patient_view
from validate import body, pagination_args, req_dt, req_string

bp = Blueprint("census", __name__)


@bp.post("/api/patients")
def create_patient():
    require_roles(["UnitNurseManager"])
    b = body()
    for f in ("mrn", "admitted_at", "unit_id"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    mrn = req_string(b, "mrn")
    admitted_at = req_dt(b, "admitted_at")
    unit_id = b.get("unit_id")
    if not isinstance(unit_id, str) or not unit_id:
        raise_err(ERR_INVALID_REQUEST, "unit_id must be a string")

    unit = db.units.get(unit_id)
    if unit is None:
        raise_err(ERR_UNIT_NOT_FOUND, "unit id does not exist")

    for p in db.patients.values():
        if p["mrn"] == mrn:
            raise_err(ERR_DUPLICATE_MRN, "another patient already uses this mrn")

    patient = new_entity({
        "mrn": mrn,
        "admitted_at": admitted_at,
        "unit_id": unit_id,
        "current_unit_id": unit_id,
        "unit_stays": [{"unit_id": unit_id, "arrived_at": admitted_at, "departed_at": None}],
        "discharged_at": None,
        "status": "ADMITTED",
    })
    db.patients[patient["id"]] = patient
    return success_object(patient_view(patient), 201)


@bp.get("/api/patients")
def list_patients():
    require_roles(ALL_ROLES)
    limit, offset = pagination_args()
    current_unit_id = request.args.get("current_unit_id")
    unit_id = request.args.get("unit_id")
    status = request.args.get("status")

    def _match(p):
        if current_unit_id is not None and p["current_unit_id"] != current_unit_id:
            return False
        if unit_id is not None:
            in_initial = p["unit_id"] == unit_id
            in_stays = any(s["unit_id"] == unit_id for s in p["unit_stays"])
            if not (in_initial or in_stays or p["current_unit_id"] == unit_id):
                return False
        if status is not None and p["status"] != status:
            return False
        return True

    items = [p for p in db.patients.values() if _match(p)]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([patient_view(p) for p in page], total, limit, offset)


@bp.get("/api/patients/<pid>")
def get_patient(pid):
    require_roles(ALL_ROLES)
    p = db.patients.get(pid)
    if p is None:
        raise_err(ERR_PATIENT_NOT_FOUND, "patient id does not exist")
    return success_object(patient_view(p))


@bp.post("/api/patients/<pid>/transfer")
def transfer_patient(pid):
    require_roles(["UnitNurseManager"])
    p = db.patients.get(pid)
    if p is None:
        raise_err(ERR_PATIENT_NOT_FOUND, "patient id does not exist")
    b = body()
    for f in ("to_unit_id", "transferred_at"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    to_unit_id = b.get("to_unit_id")
    if not isinstance(to_unit_id, str) or not to_unit_id:
        raise_err(ERR_INVALID_REQUEST, "to_unit_id must be a string")
    transferred_at = req_dt(b, "transferred_at")

    # Existence (p4) of the destination unit before state preconditions (p5).
    dest = db.units.get(to_unit_id)
    if dest is None:
        raise_err(ERR_UNIT_NOT_FOUND, "unit id does not exist")
    if p["status"] != "ADMITTED":
        raise_err(ERR_PATIENT_NOT_ADMITTED, "patient must be ADMITTED")
    if to_unit_id == p["current_unit_id"]:
        raise_err(ERR_INVALID_REQUEST, "to_unit_id must differ from current_unit_id")

    for s in p["unit_stays"]:
        if s["departed_at"] is None:
            s["departed_at"] = transferred_at
    p["unit_stays"].append({"unit_id": to_unit_id, "arrived_at": transferred_at, "departed_at": None})
    p["current_unit_id"] = to_unit_id
    touch(p)
    return success_object(patient_view(p))


@bp.post("/api/patients/<pid>/discharge")
def discharge_patient(pid):
    require_roles(["UnitNurseManager"])
    p = db.patients.get(pid)
    if p is None:
        raise_err(ERR_PATIENT_NOT_FOUND, "patient id does not exist")
    b = body()
    if "discharged_at" not in b or b["discharged_at"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: discharged_at")
    discharged_at = req_dt(b, "discharged_at")

    if p["status"] != "ADMITTED":
        raise_err(ERR_PATIENT_NOT_ADMITTED, "patient must be ADMITTED")

    for s in p["unit_stays"]:
        if s["departed_at"] is None:
            s["departed_at"] = discharged_at
    p["current_unit_id"] = None
    p["discharged_at"] = discharged_at
    p["status"] = "DISCHARGED"
    touch(p)
    return success_object(patient_view(p))


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------
@bp.post("/api/employees")
def create_employee():
    require_roles(["EmployeeHealthNurse"])
    b = body()
    for f in ("employee_code", "role_title", "home_unit_id"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    employee_code = req_string(b, "employee_code")
    role_title = req_string(b, "role_title")
    home_unit_id = b.get("home_unit_id")
    if not isinstance(home_unit_id, str) or not home_unit_id:
        raise_err(ERR_INVALID_REQUEST, "home_unit_id must be a string")
    unit = db.units.get(home_unit_id)
    if unit is None:
        raise_err(ERR_UNIT_NOT_FOUND, "unit id does not exist")

    emp = new_entity({
        "employee_code": employee_code,
        "role_title": role_title,
        "home_unit_id": home_unit_id,
    })
    db.employees[emp["id"]] = emp
    return success_object(employee_view(emp), 201)


@bp.get("/api/employees")
def list_employees():
    require_roles(ALL_ROLES)
    limit, offset = pagination_args()
    home_unit_id = request.args.get("home_unit_id")
    items = [e for e in db.employees.values() if home_unit_id is None or e["home_unit_id"] == home_unit_id]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([employee_view(e) for e in page], total, limit, offset)


@bp.get("/api/employees/<eid>")
def get_employee(eid):
    require_roles(ALL_ROLES)
    e = db.employees.get(eid)
    if e is None:
        raise_err(ERR_EMPLOYEE_NOT_FOUND, "employee id does not exist")
    return success_object(employee_view(e))
