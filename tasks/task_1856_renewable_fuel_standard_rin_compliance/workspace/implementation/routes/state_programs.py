"""StateProgram and StateCreditReport endpoints."""
from flask import Blueprint, request

import db
from errors import invalid_request, not_found, reference_not_found, invalid_state
from middleware import require_roles, json_body
from response import ok_object, ok_list, parse_pagination, paginate
from serializers import program_view, credit_report_view
from services import calculations

bp = Blueprint("state_programs", __name__)


def _get_program(program_id):
    program = db.state_programs.get(program_id)
    if program is None:
        raise not_found("State program not found")
    return program


def _get_credit_report(report_id):
    rpt = db.state_credit_reports.get(report_id)
    if rpt is None:
        raise not_found("State credit report not found")
    return rpt


@bp.route("/rfs/state-programs", methods=["POST"])
def create_program():
    require_roles("ComplianceManager")
    body = json_body()

    account_id = body.get("account_id")
    state_code = body.get("state_code")
    program_type = body.get("program_type")
    ci_standard = body.get("ci_standard_gco2e_mj")
    default_ci = body.get("default_ci_gco2e_mj")

    # --- Request shape (priority 5) ---
    for field, value in (("account_id", account_id), ("state_code", state_code),
                         ("program_type", program_type),
                         ("ci_standard_gco2e_mj", ci_standard),
                         ("default_ci_gco2e_mj", default_ci)):
        if value is None:
            raise invalid_request(f"{field} is required")
    if not isinstance(state_code, str) or len(state_code) == 0:
        raise invalid_request("state_code must be a string")
    if program_type != "LCFS":
        raise invalid_request("program_type must be LCFS")
    for name, val in (("ci_standard_gco2e_mj", ci_standard), ("default_ci_gco2e_mj", default_ci)):
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            raise invalid_request(f"{name} must be a number")

    # --- Referential integrity (priority 6) ---
    if db.compliance_accounts.get(account_id) is None:
        raise reference_not_found("Referenced account does not exist")

    # --- Uniqueness (priority 10): (account_id, state_code) unique ---
    for existing in db.state_programs.values():
        if existing["account_id"] == account_id and existing["state_code"] == state_code:
            raise invalid_request("A program for this account and state_code already exists")

    now = db.now_utc()
    program = {
        "id": db.new_id(),
        "account_id": account_id,
        "state_code": state_code,
        "program_type": program_type,
        "ci_standard_gco2e_mj": ci_standard,
        "default_ci_gco2e_mj": default_ci,
        "total_credits_tons": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.state_programs[program["id"]] = program
    return ok_object(program_view(program), status=201)


@bp.route("/rfs/state-programs/<program_id>", methods=["GET"])
def get_program(program_id):
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    return ok_object(program_view(_get_program(program_id)))


@bp.route("/rfs/state-programs", methods=["GET"])
def list_programs():
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    limit, offset = parse_pagination(request.args)
    account_id = request.args.get("account_id")
    rows = list(db.state_programs.values())
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return ok_list([program_view(r) for r in page], limit, offset, total)


@bp.route("/rfs/state-credit-reports", methods=["POST"])
def create_credit_report():
    require_roles("ComplianceManager")
    body = json_body()

    state_program_id = body.get("state_program_id")
    period_label = body.get("period_label")
    fuel_gallons = body.get("fuel_gallons")

    # --- Request shape (priority 5) ---
    for field, value in (("state_program_id", state_program_id),
                         ("period_label", period_label), ("fuel_gallons", fuel_gallons)):
        if value is None:
            raise invalid_request(f"{field} is required")
    if not isinstance(period_label, str) or len(period_label) == 0:
        raise invalid_request("period_label must be a string")
    if not isinstance(fuel_gallons, int) or isinstance(fuel_gallons, bool) or fuel_gallons <= 0:
        raise invalid_request("fuel_gallons must be a positive integer")

    # --- Referential integrity (priority 6) ---
    program = db.state_programs.get(state_program_id)
    if program is None:
        raise reference_not_found("Referenced state program does not exist")

    # --- Uniqueness (priority 10): (state_program_id, period_label) unique ---
    for existing in db.state_credit_reports.values():
        if existing["state_program_id"] == state_program_id and existing["period_label"] == period_label:
            raise invalid_request("A report for this program and period_label already exists")

    now = db.now_utc()
    credits = calculations.compute_credits_tons(
        program["ci_standard_gco2e_mj"], program["default_ci_gco2e_mj"], fuel_gallons
    )
    rpt = {
        "id": db.new_id(),
        "state_program_id": state_program_id,
        "period_label": period_label,
        "fuel_gallons": fuel_gallons,
        "status": "PROVISIONAL",
        "measured_ci_gco2e_mj": None,
        "credits_tons": credits,
        "verified_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.state_credit_reports[rpt["id"]] = rpt

    calculations.rederive_program_total(program)
    program["version"] += 1
    program["updated_at"] = now
    return ok_object(credit_report_view(rpt), status=201)


@bp.route("/rfs/state-credit-reports/<report_id>", methods=["GET"])
def get_credit_report(report_id):
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    return ok_object(credit_report_view(_get_credit_report(report_id)))


@bp.route("/rfs/state-credit-reports", methods=["GET"])
def list_credit_reports():
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    limit, offset = parse_pagination(request.args)
    state_program_id = request.args.get("state_program_id")
    rows = list(db.state_credit_reports.values())
    if state_program_id is not None:
        rows = [r for r in rows if r["state_program_id"] == state_program_id]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return ok_list([credit_report_view(r) for r in page], limit, offset, total)


@bp.route("/rfs/state-credit-reports/<report_id>/verify", methods=["POST"])
def verify_credit_report(report_id):
    require_roles("ComplianceManager")
    rpt = _get_credit_report(report_id)
    body = json_body()
    measured_ci = body.get("measured_ci_gco2e_mj")
    if not isinstance(measured_ci, (int, float)) or isinstance(measured_ci, bool) or measured_ci <= 0:
        raise invalid_request("measured_ci_gco2e_mj must be a positive number")
    if rpt["status"] != "PROVISIONAL":
        raise invalid_state("State credit report is not PROVISIONAL")

    program = db.state_programs[rpt["state_program_id"]]
    now = db.now_utc()
    rpt["measured_ci_gco2e_mj"] = measured_ci
    rpt["credits_tons"] = calculations.compute_credits_tons(
        program["ci_standard_gco2e_mj"], measured_ci, rpt["fuel_gallons"]
    )
    rpt["status"] = "VERIFIED"
    rpt["verified_at"] = now
    rpt["version"] += 1
    rpt["updated_at"] = now

    calculations.rederive_program_total(program)
    program["version"] += 1
    program["updated_at"] = now
    return ok_object(credit_report_view(rpt))
