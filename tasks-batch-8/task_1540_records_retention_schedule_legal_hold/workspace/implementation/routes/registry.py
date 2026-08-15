"""Governance programs, record classes, jurisdictions, custodians."""
from flask import Blueprint, request

from db import db, new_id, touch
from errors import err, not_found
from middleware import authenticate, body_json, ALL_ROLES
from response import success_object, success_list, paginate
from serializers import (
    program_view, record_class_view, jurisdiction_view, custodian_view)
from utils import check_str, check_int, check_number, check_enum

bp = Blueprint("registry", __name__)

DAYS_IN_MONTH = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
                 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


# ---------------------------------------------------------------------------
# Governance Programs
# ---------------------------------------------------------------------------
@bp.route("/ig/programs", methods=["POST"])
def create_program():
    authenticate(["PlatformAdmin"])
    body = body_json()
    name = check_str(body, "name")
    fye_month = check_int(body, "fiscal_year_end_month", minimum=1)
    if fye_month > 12:
        raise err("ERR_INVALID_REQUEST", 400,
                  "fiscal_year_end_month must be between 1 and 12")
    fye_day = check_int(body, "fiscal_year_end_day", minimum=1)
    if fye_day > DAYS_IN_MONTH[fye_month]:
        raise err("ERR_INVALID_REQUEST", 400,
                  "fiscal_year_end_day is not valid for the named month")
    ack_deadline_days = check_int(body, "ack_deadline_days", required=False,
                                  minimum=0, min_exclusive=True)
    reminder_interval_days = check_int(body, "reminder_interval_days",
                                       required=False, minimum=0,
                                       min_exclusive=True)
    max_reminders = check_int(body, "max_reminders_before_escalation",
                              required=False, minimum=1)
    stale_hold_days = check_int(body, "stale_hold_days", required=False,
                                minimum=0, min_exclusive=True)
    warn_pct = check_number(body, "over_preservation_warn_pct", required=False)
    ack_sla_mode = check_enum(body, "ack_sla_mode",
                              {"STRICT", "REMINDER_ADJUSTED"}, required=False,
                              default="STRICT")
    p = {
        "id": new_id(),
        "name": name,
        "fiscal_year_end_month": fye_month,
        "fiscal_year_end_day": fye_day,
        "ack_deadline_days": 14 if ack_deadline_days is None else ack_deadline_days,
        "reminder_interval_days": 7 if reminder_interval_days is None else reminder_interval_days,
        "max_reminders_before_escalation": 3 if max_reminders is None else max_reminders,
        "stale_hold_days": 180 if stale_hold_days is None else stale_hold_days,
        "over_preservation_warn_pct": 20 if warn_pct is None else warn_pct,
        "ack_sla_mode": ack_sla_mode or "STRICT",
    }
    touch(p)
    db.programs[p["id"]] = p
    return success_object(program_view(p), 201)


@bp.route("/ig/programs", methods=["GET"])
def list_programs():
    authenticate(ALL_ROLES)
    window, limit, offset, total = paginate(list(db.programs.values()),
                                            request.args)
    return success_list([program_view(p) for p in window], limit, offset, total)


@bp.route("/ig/programs/<programId>", methods=["GET"])
def get_program(programId):
    authenticate(ALL_ROLES)
    p = db.programs.get(programId)
    if p is None:
        not_found("Program not found")
    return success_object(program_view(p))


# ---------------------------------------------------------------------------
# Record Classes
# ---------------------------------------------------------------------------
@bp.route("/ig/record-classes", methods=["POST"])
def create_record_class():
    authenticate(["PlatformAdmin"])
    body = body_json()
    program_id = check_str(body, "program_id")
    code = check_str(body, "code")
    name = check_str(body, "name")
    cost = check_number(body, "monthly_storage_cost_cents_per_gb",
                        minimum=0, min_exclusive=True)
    if program_id not in db.programs:
        raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", 404,
                  "Referenced program does not exist")
    for c in db.record_classes.values():
        if c["program_id"] == program_id and c["code"] == code:
            raise err("ERR_DUPLICATE_CODE", 409,
                      "Record class code already exists in the program")
    c = {"id": new_id(), "program_id": program_id, "code": code, "name": name,
         "monthly_storage_cost_cents_per_gb": cost}
    touch(c)
    db.record_classes[c["id"]] = c
    return success_object(record_class_view(c), 201)


@bp.route("/ig/record-classes", methods=["GET"])
def list_record_classes():
    authenticate(ALL_ROLES)
    items = list(db.record_classes.values())
    pid = request.args.get("program_id")
    if pid is not None:
        items = [c for c in items if c["program_id"] == pid]
    window, limit, offset, total = paginate(items, request.args)
    return success_list([record_class_view(c) for c in window], limit, offset, total)


@bp.route("/ig/record-classes/<classId>", methods=["GET"])
def get_record_class(classId):
    authenticate(ALL_ROLES)
    c = db.record_classes.get(classId)
    if c is None:
        not_found("Record class not found")
    return success_object(record_class_view(c))


# ---------------------------------------------------------------------------
# Jurisdictions
# ---------------------------------------------------------------------------
@bp.route("/ig/jurisdictions", methods=["POST"])
def create_jurisdiction():
    authenticate(["PlatformAdmin"])
    body = body_json()
    program_id = check_str(body, "program_id")
    code = check_str(body, "code")
    name = check_str(body, "name")
    if program_id not in db.programs:
        raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", 404,
                  "Referenced program does not exist")
    for j in db.jurisdictions.values():
        if j["program_id"] == program_id and j["code"] == code:
            raise err("ERR_DUPLICATE_CODE", 409,
                      "Jurisdiction code already exists in the program")
    j = {"id": new_id(), "program_id": program_id, "code": code, "name": name}
    touch(j)
    db.jurisdictions[j["id"]] = j
    return success_object(jurisdiction_view(j), 201)


@bp.route("/ig/jurisdictions", methods=["GET"])
def list_jurisdictions():
    authenticate(ALL_ROLES)
    items = list(db.jurisdictions.values())
    pid = request.args.get("program_id")
    if pid is not None:
        items = [j for j in items if j["program_id"] == pid]
    window, limit, offset, total = paginate(items, request.args)
    return success_list([jurisdiction_view(j) for j in window], limit, offset, total)


@bp.route("/ig/jurisdictions/<jurisdictionId>", methods=["GET"])
def get_jurisdiction(jurisdictionId):
    authenticate(ALL_ROLES)
    j = db.jurisdictions.get(jurisdictionId)
    if j is None:
        not_found("Jurisdiction not found")
    return success_object(jurisdiction_view(j))


# ---------------------------------------------------------------------------
# Custodians
# ---------------------------------------------------------------------------
@bp.route("/ig/custodians", methods=["POST"])
def create_custodian():
    authenticate(["RecordsManager"])
    body = body_json()
    program_id = check_str(body, "program_id")
    email = check_str(body, "email")
    full_name = check_str(body, "full_name")
    department = check_str(body, "department")
    if program_id not in db.programs:
        raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", 404,
                  "Referenced program does not exist")
    for c in db.custodians.values():
        if c["program_id"] == program_id and c["email"] == email:
            raise err("ERR_DUPLICATE_CUSTODIAN", 409,
                      "Custodian email already exists in the program")
    c = {"id": new_id(), "program_id": program_id, "email": email,
         "full_name": full_name, "department": department}
    touch(c)
    db.custodians[c["id"]] = c
    return success_object(custodian_view(c), 201)


@bp.route("/ig/custodians", methods=["GET"])
def list_custodians():
    authenticate(ALL_ROLES)
    items = list(db.custodians.values())
    pid = request.args.get("program_id")
    if pid is not None:
        items = [c for c in items if c["program_id"] == pid]
    window, limit, offset, total = paginate(items, request.args)
    return success_list([custodian_view(c) for c in window], limit, offset, total)


@bp.route("/ig/custodians/<custodianId>", methods=["GET"])
def get_custodian(custodianId):
    authenticate(ALL_ROLES)
    c = db.custodians.get(custodianId)
    if c is None:
        not_found("Custodian not found")
    return success_object(custodian_view(c))
