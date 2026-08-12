"""Employees: the entity-backed identity behind Operator / QualityTech (PRD 2.1)."""
from flask import Blueprint

from db import STORE, make_record
from envelope import success
from errors import ApiError
from middleware import authenticate, authorize
from services import ser_employee
from validation import get_body, req_str, req_enum

bp = Blueprint("employees", __name__)


@bp.post("/api/employees")
def create_employee():
    uid, role = authenticate()
    data = get_body()
    full_name = req_str(data, "full_name")
    capability = req_enum(data, "capability", ("OPERATOR", "QUALITY_TECH", "DUAL"))
    authorize(role, uid, {"MillManager"})
    rec = make_record()
    rec.update(full_name=full_name, capability=capability)
    STORE["employees"][rec["id"]] = rec
    return success(ser_employee(rec), 201)


@bp.get("/api/employees/<eid>")
def get_employee(eid):
    uid, role = authenticate()
    authorize(role, uid, {"MillManager"})
    emp = STORE["employees"].get(eid)
    if emp is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Employee {eid} not found")
    return success(ser_employee(emp), 200)
