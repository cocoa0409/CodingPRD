"""Reports: intake, screening fork (PRD 3.1, 3.2)."""
from flask import Blueprint, request

from store import store
from errors import ApiError
from envelope import success
from helpers import (authenticate, authorize, get_body, require_str, require_array,
                     optional_str, check_enum, resolve, resolve_body_id, base_fields,
                     touch, paginate, sort_key, serialize)
from calc import response_due_at

bp = Blueprint("reports", __name__)

REPORTER_TYPES = {"MANDATORY", "VOLUNTARY", "ANONYMOUS"}
PRIORITIES = {"EMERGENCY", "PRIORITY", "ROUTINE"}
ALLEGATIONS = {"PHYSICAL_ABUSE", "NEGLECT", "FINANCIAL_EXPLOITATION",
               "EMOTIONAL_ABUSE", "SELF_NEGLECT"}
DECISIONS = {"SCREEN_IN", "SCREEN_OUT"}


def new_case(report):
    case = base_fields()
    case.update({
        "report_id": report["id"],
        "client_id": report["client_id"],
        "status": "OPEN",
        "allegation_types": list(report["allegation_types"]),
        "risk_level": None,
        "estimated_exposure_cents": 0,
        "substantiated_exposure_cents": 0,
        "frozen_account_count": 0,
        "cross_report_agency": None,
        "cross_reported_at": None,
        "guardianship_status": "NONE",
        "service_plan_status": "NONE",
        "benefit_programs": [],
        "closed_at": None,
        "closure_reason": None,
    })
    store.cases[case["id"]] = case
    return case


@bp.post("/reports")
def create_report():
    uid, role = authenticate()
    authorize(role, {"IntakeWorker"})
    body = get_body()
    resolve_body_id(body, "client_id", "client")
    client_id = require_str(body, "client_id")
    reporter_type = require_str(body, "reporter_type")
    allegation_types = require_array(body, "allegation_types")
    priority = require_str(body, "priority")
    narrative = require_str(body, "narrative")
    reporter_name = optional_str(body, "reporter_name", None)
    # enum checks
    check_enum(reporter_type, REPORTER_TYPES)
    check_enum(priority, PRIORITIES)
    if len(allegation_types) == 0:
        raise ApiError("ERR_INVALID_ENUM", "allegation_types must be non-empty", 422)
    for a in allegation_types:
        check_enum(a, ALLEGATIONS)

    report = base_fields()
    report.update({
        "client_id": client_id,
        "reporter_type": reporter_type,
        "reporter_name": reporter_name,
        "allegation_types": list(allegation_types),
        "priority": priority,
        "narrative": narrative,
        "status": "RECEIVED",
        "response_due_at": response_due_at(report["created_at"], priority),
        "screening_overdue": False,
        "screen_out_reason": None,
        "case_id": None,
    })
    store.reports[report["id"]] = report
    return success(serialize(report, "report")), 201


@bp.get("/reports/<rid>")
def get_report(rid):
    uid, role = authenticate()
    authorize(role, {"IntakeWorker", "Supervisor", "Caseworker"})
    report = resolve("report", rid)
    return success(serialize(report, "report")), 200


@bp.get("/reports")
def list_reports():
    uid, role = authenticate()
    authorize(role, {"IntakeWorker", "Supervisor"})
    items = list(store.reports.values())
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    if client_id is not None:
        items = [r for r in items if r["client_id"] == client_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=sort_key)
    page, pag = paginate(items)
    return success([serialize(r, "report") for r in page], "array", pag), 200


@bp.post("/reports/<rid>/screen")
def screen_report(rid):
    uid, role = authenticate()
    authorize(role, {"Supervisor"})
    report = resolve("report", rid)
    body = get_body()
    decision = require_str(body, "decision")
    check_enum(decision, DECISIONS)
    if report["status"] != "RECEIVED":
        raise ApiError("ERR_REPORT_INVALID_STATE", "Report is not RECEIVED", 409)

    overdue = store.clock > report["response_due_at"]
    report["screening_overdue"] = overdue

    if decision == "SCREEN_IN":
        client = resolve("client", report["client_id"])
        case = new_case(report)
        report["case_id"] = case["id"]
        report["status"] = "SCREENED_IN"
        touch(report)
        if client["status"] == "INTAKE":
            client["status"] = "UNDER_INVESTIGATION"
        client["open_case_count"] += 1
        touch(client)
    else:  # SCREEN_OUT
        report["screen_out_reason"] = optional_str(body, "screen_out_reason", None)
        report["status"] = "SCREENED_OUT"
        touch(report)

    return success(serialize(report, "report")), 200
