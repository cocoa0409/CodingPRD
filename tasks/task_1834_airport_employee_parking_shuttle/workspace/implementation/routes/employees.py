"""Employee endpoints."""
from flask import Blueprint, request

import db
from db import fmt_dt, now, parse_date, touch
from domain import get_or_404, serialize_employee, employee_standing, employee_balance_due
from errors import raise_error
from middleware import require_roles
from response import success_object, success_list
from pagination import parse_pagination

bp = Blueprint("employees", __name__)

ALL_ROLES = ("ParkingAdmin", "Employee", "PayrollAdmin",
             "EnforcementOfficer", "AppealsOfficer", "ShuttleDispatcher")

SHIFT_PATTERNS = {"DAY", "NIGHT", "ROTATING", "SPLIT"}


@bp.route("/parking/employees", methods=["POST"])
def create_employee():
    require_roles("ParkingAdmin")
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    for field in ("program_id", "badge_number", "full_name", "employer_code", "shift_pattern", "hire_date"):
        if body.get(field) is None:
            raise_error("ERR_INVALID_REQUEST", f"{field} is required")
    program = get_or_404(db.programs, body["program_id"])
    if body["shift_pattern"] not in SHIFT_PATTERNS:
        raise_error("ERR_INVALID_REQUEST", "invalid shift_pattern")
    if parse_date(body["hire_date"]) is None:
        raise_error("ERR_INVALID_REQUEST", "hire_date must be an ISO date (YYYY-MM-DD)")
    # badge unique per program
    for e in db.employees.values():
        if e["program_id"] == program["id"] and e["badge_number"] == body["badge_number"]:
            raise_error("ERR_BADGE_NUMBER_TAKEN", "badge_number already used in this program")
    rec = db.new_record({
        "program_id": program["id"],
        "badge_number": body["badge_number"],
        "full_name": body["full_name"],
        "employer_code": body["employer_code"],
        "shift_pattern": body["shift_pattern"],
        "hire_date": body["hire_date"],
        "employment_status": "ACTIVE",
        "terminated_at": None,
    })
    db.employees[rec["id"]] = rec
    return success_object(serialize_employee(rec), 201)


@bp.route("/parking/employees/<eid>", methods=["GET"])
def get_employee(eid):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.employees, eid)
    return success_object(serialize_employee(rec), 200)


@bp.route("/parking/employees", methods=["GET"])
def list_employees():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    program_id = request.args.get("program_id")
    shift_pattern = request.args.get("shift_pattern")
    standing = request.args.get("standing")
    employment_status = request.args.get("employment_status")
    items = sorted(db.employees.values(), key=lambda e: e["created_at"])
    out = []
    for e in items:
        if program_id is not None and e["program_id"] != program_id:
            continue
        if shift_pattern is not None and e["shift_pattern"] != shift_pattern:
            continue
        if employment_status is not None and e["employment_status"] != employment_status:
            continue
        if standing is not None and employee_standing(e["id"]) != standing:
            continue
        out.append(serialize_employee(e))
    total = len(out)
    return success_list(out[offset:offset + limit], limit, offset, total)


@bp.route("/parking/employees/<eid>/terminate", methods=["POST"])
def terminate_employee(eid):
    require_roles("ParkingAdmin")
    rec = get_or_404(db.employees, eid)
    if rec["employment_status"] == "TERMINATED":
        raise_error("ERR_INVALID_STATE", "Employee already terminated")
    rec["employment_status"] = "TERMINATED"
    rec["terminated_at"] = fmt_dt(now())
    touch(rec)
    return success_object(serialize_employee(rec), 200)
