"""VolunteerLog endpoints and dollars-for-doers grants (PRD §3.7)."""
from flask import Blueprint, request

from db import db, parse_iso
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_CHARITY_NOT_APPROVED,
    ERR_EMPLOYEE_NOT_ACTIVE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_LOG_DISBURSED,
)
from middleware import get_user_context, require_role
from response import object_response, array_response
from services.common import (
    get_json_body,
    require_fields,
    require_string,
    require_positive_int,
    require_datetime,
    stamp_create,
    touch,
    serialize,
    find_or_404,
    paginate,
)
from services.calc import dollars_for_doers_grant
from services.queries import grants_referencing_source

bp = Blueprint("volunteer_logs", __name__)


@bp.route("/volunteer-logs", methods=["POST"])
def log_volunteer():
    uid, role = get_user_context()
    require_role(role, {"Employee", "GivingAdmin"})
    body = get_json_body()
    require_fields(body, ["program_id", "employee_id", "charity_id", "minutes", "activity_date"])
    program_id = require_string(body, "program_id")
    employee_id = require_string(body, "employee_id")
    charity_id = require_string(body, "charity_id")
    minutes = require_positive_int(body, "minutes")
    activity_date = require_datetime(body, "activity_date")

    program = find_or_404(db.programs, program_id)
    find_or_404(db.employees, employee_id)
    find_or_404(db.charities, charity_id)

    if role == "Employee" and uid != employee_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Employee may only log own volunteer time")

    # activity_date must fall within the program tax_year (body well-formedness).
    if parse_iso(activity_date).year != program["tax_year"]:
        raise err(ERR_INVALID_REQUEST, "activity_date must fall within the program tax_year")

    rec = {
        "program_id": program_id,
        "employee_id": employee_id,
        "charity_id": charity_id,
        "minutes": minutes,
        "activity_date": activity_date,
        "raw_grant_cents": 0,
        "grant_amount_cents": 0,
        "status": "LOGGED",
    }
    stamp_create(rec)
    db.volunteer_logs[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/volunteer-logs/<log_id>", methods=["GET"])
def get_log(log_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager", "Employee"})
    rec = find_or_404(db.volunteer_logs, log_id)
    return object_response(serialize(rec), 200)


@bp.route("/volunteer-logs", methods=["GET"])
def list_logs():
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager", "Employee"})
    program_id = request.args.get("program_id")
    employee_id = request.args.get("employee_id")
    charity_id = request.args.get("charity_id")
    status = request.args.get("status")
    items = []
    for log in db.volunteer_logs.values():
        if program_id is not None and log["program_id"] != program_id:
            continue
        if employee_id is not None and log["employee_id"] != employee_id:
            continue
        if charity_id is not None and log["charity_id"] != charity_id:
            continue
        if status is not None and log["status"] != status:
            continue
        items.append(log)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(log) for log in page], limit, offset, total, 200)


@bp.route("/volunteer-logs/<log_id>/approve", methods=["POST"])
def approve_log(log_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    rec = find_or_404(db.volunteer_logs, log_id)
    if rec["status"] != "LOGGED":
        raise err(ERR_INVALID_STATE, "Log must be LOGGED to approve")
    charity = db.charities.get(rec["charity_id"])
    if charity is None or charity["status"] != "APPROVED":
        raise err(ERR_CHARITY_NOT_APPROVED, "Referenced charity must be APPROVED")
    employee = db.employees.get(rec["employee_id"])
    if employee is None or employee["status"] != "ACTIVE":
        raise err(ERR_EMPLOYEE_NOT_ACTIVE, "Volunteer employee must be ACTIVE")
    program = db.programs.get(rec["program_id"])
    raw, grant = dollars_for_doers_grant(program, rec["minutes"], employee["dfd_consumed_ytd_cents"])
    rec["raw_grant_cents"] = raw
    rec["grant_amount_cents"] = grant
    rec["status"] = "APPROVED"
    touch(rec)
    employee["dfd_consumed_ytd_cents"] += grant
    touch(employee)
    return object_response(serialize(rec), 200)


@bp.route("/volunteer-logs/<log_id>/reject", methods=["POST"])
def reject_log(log_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    rec = find_or_404(db.volunteer_logs, log_id)
    if rec["status"] != "LOGGED":
        raise err(ERR_INVALID_STATE, "Log must be LOGGED to reject")
    rec["status"] = "REJECTED"
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/volunteer-logs/<log_id>/reverse", methods=["POST"])
def reverse_log(log_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    rec = find_or_404(db.volunteer_logs, log_id)
    if rec["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "Log must be APPROVED to reverse")
    if grants_referencing_source("DFD", log_id, {"STAGED", "SETTLED"}):
        raise err(ERR_LOG_DISBURSED, "Cannot reverse a log whose grant is staged or settled")
    rec["status"] = "REVERSED"
    touch(rec)
    employee = db.employees.get(rec["employee_id"])
    if employee is not None:
        employee["dfd_consumed_ytd_cents"] -= rec["grant_amount_cents"]
        touch(employee)
    return object_response(serialize(rec), 200)
