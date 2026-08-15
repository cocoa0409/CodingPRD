"""SavingsReport endpoints (PRD 3.8)."""
from flask import Blueprint

from db import new_record, store, touch
from domain import (
    accounts_of_program, bump_program, fill_report_computed, post_budget,
    require_active, ser_report,
)
from errors import raise_error
from middleware import ALL_ROLES, get_caller, locked, require_roles
from response import success_object
from validate import get_body, req_enum, req_int, req_period, req_str
from routes.common import list_endpoint, require_record

bp = Blueprint("reports", __name__)

PM = ["ProgramManager"]
AUDITOR = ["Auditor"]
METHODS = ["ENGINEERING_ESTIMATE", "METERED_ACTUAL"]


@bp.route("/streetlights/savings-reports", methods=["POST"])
@locked
def create_report():
    caller = get_caller()
    body = get_body()
    program_id = req_str(body, "program_id")
    period = req_period(body, "period")
    method = req_enum(body, "method", METHODS)
    fiscal_year_label = req_str(body, "fiscal_year_label")
    expected_program_version = req_int(body, "expected_program_version")
    require_roles(caller, PM)
    program = store.programs.get(program_id)
    if program is None:
        raise_error("ERR_PROGRAM_NOT_FOUND", f"program not found: {program_id}")
    # Stage 7 OCC (before program-lifecycle and business checks, PRD 2.10).
    if expected_program_version != program["version"]:
        raise_error("ERR_STALE_VERSION",
                    "expected_program_version does not match the program's version")
    require_active(program)
    for r in store.reports.values():
        if (r["program_id"] == program_id and r["period"] == period
                and r["status"] == "ATTESTED"):
            raise_error("ERR_REPORT_PERIOD_FINALIZED",
                        "an ATTESTED report already exists for this program and period")
    for r in store.reports.values():
        if (r["program_id"] == program_id and r["period"] == period
                and r["status"] in ("DRAFT", "REJECTED")):
            r["status"] = "SUPERSEDED"
            touch(r)
    rec = new_record("reports", {
        "program_id": program_id,
        "period": period,
        "method": method,
        "fiscal_year_label": fiscal_year_label,
        "baseline_kwh": 0.0,
        "actual_kwh": 0.0,
        "savings_kwh": 0.0,
        "raw_credit_cents": 0,
        "attested_credit_cents": None,
        "submitted_by_user_id": None,
        "attested_by_user_id": None,
        "status": "DRAFT",
    })
    fill_report_computed(rec, program)
    bump_program(program)
    return success_object(ser_report(rec), status=201)


@bp.route("/streetlights/savings-reports", methods=["GET"])
@locked
def list_reports():
    return list_endpoint("reports", ser_report, ["program_id", "period", "status"])


@bp.route("/streetlights/savings-reports/<rid>", methods=["GET"])
@locked
def get_report(rid):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    rec = require_record("reports", rid, "ERR_REPORT_NOT_FOUND")
    return success_object(ser_report(rec))


@bp.route("/streetlights/savings-reports/<rid>/submit", methods=["POST"])
@locked
def submit_report(rid):
    caller = get_caller()
    require_roles(caller, PM)
    report = require_record("reports", rid, "ERR_REPORT_NOT_FOUND")
    require_active(store.programs.get(report["program_id"]))
    if report["status"] != "DRAFT":
        raise_error("ERR_REPORT_NOT_DRAFT", "submit requires a DRAFT report")
    # Books must be closed under the period: every account past the period,
    # with no ESTIMATED lines left in it.
    for account in accounts_of_program(report["program_id"]):
        if account["current_period"] <= report["period"]:
            raise_error("ERR_REPORT_PERIOD_OPEN",
                        "an account's current period has not advanced past the report period")
        if any(l for l in store.billing_lines.values()
               if l["account_id"] == account["id"] and l["period"] == report["period"]
               and l["status"] == "ESTIMATED"):
            raise_error("ERR_REPORT_PERIOD_OPEN",
                        "an account still has ESTIMATED lines in the report period")
    report["submitted_by_user_id"] = caller.user_id
    report["status"] = "SUBMITTED"
    touch(report)
    return success_object(ser_report(report))


@bp.route("/streetlights/savings-reports/<rid>/attest", methods=["POST"])
@locked
def attest_report(rid):
    caller = get_caller()
    require_roles(caller, AUDITOR)
    report = require_record("reports", rid, "ERR_REPORT_NOT_FOUND")
    # Stage 6 segregation of duties, before program-lifecycle and state.
    if report["submitted_by_user_id"] is not None and caller.user_id == report["submitted_by_user_id"]:
        raise_error("ERR_SEGREGATION_OF_DUTIES", "the submitter may not attest the report")
    program = store.programs.get(report["program_id"])
    require_active(program)
    if report["status"] != "SUBMITTED":
        raise_error("ERR_REPORT_NOT_SUBMITTED", "attest requires a SUBMITTED report")
    # incentive_rebate_credit: pinned evaluation order (PRD 3.8).
    fy_credited = sum(r["attested_credit_cents"] for r in store.reports.values()
                      if r["id"] != report["id"]
                      and r["program_id"] == report["program_id"]
                      and r["fiscal_year_label"] == report["fiscal_year_label"]
                      and r["status"] == "ATTESTED")
    remaining = max(0, program["fy_rebate_cap_cents"] - fy_credited)
    attested = min(report["raw_credit_cents"], remaining)
    report["attested_credit_cents"] = attested
    report["attested_by_user_id"] = caller.user_id
    report["status"] = "ATTESTED"
    touch(report)
    post_budget(program, attested)
    bump_program(program)
    return success_object(ser_report(report))


@bp.route("/streetlights/savings-reports/<rid>/reject", methods=["POST"])
@locked
def reject_report(rid):
    caller = get_caller()
    require_roles(caller, AUDITOR)
    report = require_record("reports", rid, "ERR_REPORT_NOT_FOUND")
    if report["submitted_by_user_id"] is not None and caller.user_id == report["submitted_by_user_id"]:
        raise_error("ERR_SEGREGATION_OF_DUTIES", "the submitter may not reject the report")
    require_active(store.programs.get(report["program_id"]))
    if report["status"] != "SUBMITTED":
        raise_error("ERR_REPORT_NOT_SUBMITTED", "reject requires a SUBMITTED report")
    report["status"] = "REJECTED"
    touch(report)
    return success_object(ser_report(report))


@bp.route("/streetlights/savings-reports/<rid>/revise", methods=["POST"])
@locked
def revise_report(rid):
    caller = get_caller()
    require_roles(caller, PM)
    report = require_record("reports", rid, "ERR_REPORT_NOT_FOUND")
    program = store.programs.get(report["program_id"])
    require_active(program)
    if report["status"] != "REJECTED":
        raise_error("ERR_REPORT_NOT_DRAFT", "revise requires a REJECTED report")
    report["status"] = "DRAFT"
    report["submitted_by_user_id"] = None
    fill_report_computed(report, program)
    touch(report)
    return success_object(ser_report(report))
