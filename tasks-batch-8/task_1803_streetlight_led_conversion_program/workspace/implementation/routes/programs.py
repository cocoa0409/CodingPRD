"""ConversionProgram endpoints (PRD 3.1)."""
from flask import Blueprint

from db import new_record, store, touch
from domain import require_active, routes_of_program, ser_program
from errors import raise_error
from middleware import ALL_ROLES, get_caller, locked, require_roles
from response import success_object
from validate import get_body, req_int, req_str
from routes.common import list_endpoint, require_record

bp = Blueprint("programs", __name__)

PM = ["ProgramManager"]


@bp.route("/streetlights/programs", methods=["POST"])
@locked
def create_program():
    caller = get_caller()
    body = get_body()
    program_name = req_str(body, "program_name")
    budget = req_int(body, "program_budget_cents", positive=True)
    rebate_cap = req_int(body, "fy_rebate_cap_cents", positive=True)
    rebate_rate = req_int(body, "rebate_cents_per_kwh", positive=True)
    require_roles(caller, PM)
    rec = new_record("programs", {
        "program_name": program_name,
        "program_budget_cents": budget,
        "fy_rebate_cap_cents": rebate_cap,
        "rebate_cents_per_kwh": rebate_rate,
        "budget_balance_cents": budget,
        "status": "DRAFT",
    })
    return success_object(ser_program(rec), status=201)


@bp.route("/streetlights/programs", methods=["GET"])
@locked
def list_programs():
    return list_endpoint("programs", ser_program, ["status"])


@bp.route("/streetlights/programs/<pid>", methods=["GET"])
@locked
def get_program(pid):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    rec = require_record("programs", pid, "ERR_PROGRAM_NOT_FOUND")
    return success_object(ser_program(rec))


@bp.route("/streetlights/programs/<pid>/summary", methods=["GET"])
@locked
def get_program_summary(pid):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    rec = require_record("programs", pid, "ERR_PROGRAM_NOT_FOUND")
    s = ser_program(rec)
    return success_object({
        "budget_balance_cents": s["budget_balance_cents"],
        "current_billing_run_estimated_cents": s["current_billing_run_estimated_cents"],
        "converted_pole_count": s["converted_pole_count"],
        "pending_salvage_item_count": s["pending_salvage_item_count"],
        "status": s["status"],
    })


@bp.route("/streetlights/programs/<pid>/activate", methods=["POST"])
@locked
def activate_program(pid):
    caller = get_caller()
    require_roles(caller, PM)
    rec = require_record("programs", pid, "ERR_PROGRAM_NOT_FOUND")
    if rec["status"] != "DRAFT":
        raise_error("ERR_INVALID_REQUEST", "only a DRAFT program can be activated")
    rec["status"] = "ACTIVE"
    touch(rec)
    return success_object(ser_program(rec))


@bp.route("/streetlights/programs/<pid>/close", methods=["POST"])
@locked
def close_program(pid):
    caller = get_caller()
    require_roles(caller, PM)
    rec = require_record("programs", pid, "ERR_PROGRAM_NOT_FOUND")
    if rec["status"] != "ACTIVE":
        raise_error("ERR_INVALID_REQUEST", "only an ACTIVE program can be closed")
    for route in routes_of_program(rec["id"]):
        if route["status"] not in ("CLOSED", "CANCELLED"):
            raise_error("ERR_ROUTES_STILL_ACTIVE", "all conversion routes must be CLOSED or CANCELLED")
    rec["status"] = "CLOSED"
    touch(rec)
    return success_object(ser_program(rec))
