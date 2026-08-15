"""Physician interpretation reports (PRD 3.6)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_FINAL_REPORT_EXISTS,
    ERR_STUDY_NOT_SCORED,
    ERR_INVALID_PRIMARY_TASK,
    ERR_NOT_REPORT_AUTHOR,
    ERR_REPORT_INVALID_STATE,
    ERR_SOD_REPORT_SCORER,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public, query_filters
from services.calculations import classify_severity, compute_turnaround
from services.core import new_record, touch
from util import CLOCK
from validate import get_body, req_str, req_int, require_path_resource, require_body_ref

bp = Blueprint("reports", __name__)

LIVE_REPORT_STATES = {"SIGNED", "FINALIZED", "ADDENDUM_OPEN"}


def _check_author(caller, report):
    if caller.user_id != report["physician_id"]:
        raise_error(ERR_NOT_REPORT_AUTHOR, "X-User-ID must equal the report's physician_id")


@bp.post("/interpretation-reports")
def create_report():
    caller = authorized(["InterpretingPhysician"])
    body = get_body()
    # Priority 3: body FK existence in declaration order (study_id, primary_scoring_task_id).
    study = require_body_ref("sleep_studies", body.get("study_id"))
    task = require_body_ref("scoring_tasks", body.get("primary_scoring_task_id"))
    # Priority 4: shape.
    study_id = req_str(body, "study_id")
    primary_scoring_task_id = req_str(body, "primary_scoring_task_id")
    diagnosis_code = req_str(body, "diagnosis_code")
    expected_version = req_int(body, "expected_sleep_study_version")
    # Priority 6: optimistic concurrency on the study.
    if expected_version != study["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_sleep_study_version does not match the study's current version")
    # Priority 7: state group — live final report first, then study phase.
    for existing in db["interpretation_reports"].values():
        if existing["study_id"] == study_id and existing["status"] in LIVE_REPORT_STATES:
            raise_error(ERR_FINAL_REPORT_EXISTS,
                        "a SIGNED/FINALIZED/ADDENDUM_OPEN report already exists for the study")
    if study["status"] not in ("SCORED", "INTERPRETATION_IN_PROGRESS"):
        raise_error(ERR_STUDY_NOT_SCORED,
                    f"report creation requires SCORED or INTERPRETATION_IN_PROGRESS, found {study['status']}")
    # Priority 9: the named task must be the study's ACCEPTED PRIMARY.
    if not (task["study_id"] == study_id
            and task["assignment_kind"] == "PRIMARY"
            and task["status"] == "ACCEPTED"):
        raise_error(ERR_INVALID_PRIMARY_TASK,
                    "primary_scoring_task_id is not the ACCEPTED PRIMARY task of the study")
    # Supersede any existing DRAFT report for the study.
    for existing in db["interpretation_reports"].values():
        if existing["study_id"] == study_id and existing["status"] == "DRAFT":
            existing["status"] = "SUPERSEDED"
            touch(existing)
    rec = new_record("interpretation_reports", {
        "study_id": study_id,
        "physician_id": caller.user_id,
        "primary_scoring_task_id": primary_scoring_task_id,
        "diagnosis_code": diagnosis_code,
        "index_at_interpretation": None,
        "severity": None,
        "turnaround_business_hours": None,
        "turnaround_calendar_hours": None,
        "sla_breached": None,
        "signed_at": None,
        "finalized_at": None,
        "addendum_count": 0,
        "status": "DRAFT",
    })
    study["status"] = "INTERPRETATION_IN_PROGRESS"
    touch(study)
    return success_object(public(rec), status=201)


@bp.get("/interpretation-reports")
def list_reports():
    return list_response("interpretation_reports",
                         query_filters("study_id", "physician_id", "primary_scoring_task_id"))


@bp.get("/interpretation-reports/<interpretationReportId>")
def get_report(interpretationReportId):
    return get_one("interpretation_reports", interpretationReportId)


@bp.post("/interpretation-reports/<interpretationReportId>/sign")
def sign_report(interpretationReportId):
    caller = authorized(["InterpretingPhysician"])
    report = require_path_resource("interpretation_reports", interpretationReportId)
    _check_author(caller, report)
    if report["status"] != "DRAFT":
        raise_error(ERR_REPORT_INVALID_STATE,
                    f"sign requires DRAFT, found {report['status']}")
    study = db["sleep_studies"].get(report["study_id"])
    task = db["scoring_tasks"].get(report["primary_scoring_task_id"])
    # Priority 8: segregation of duties at the pen — signer npi != primary scorer npi.
    physician = db["physicians"].get(caller.user_id)
    scorer = db["scorers"].get(task["scorer_id"]) if task is not None else None
    physician_npi = physician["npi"] if physician is not None else None
    scorer_npi = scorer["npi"] if scorer is not None else None
    if physician_npi is not None and physician_npi == scorer_npi:
        raise_error(ERR_SOD_REPORT_SCORER,
                    "report signer npi equals the ACCEPTED PRIMARY task scorer's npi")
    # Severity against the accepted index (REI for HST, AHI otherwise).
    if study["study_type"] == "HST":
        idx = study["accepted_rei"]
    else:
        idx = study["accepted_ahi"]
    report["index_at_interpretation"] = idx
    report["severity"] = classify_severity(idx)
    # Turnaround and SLA verdict against the ordering priority.
    order = db["referral_orders"].get(study["order_id"])
    priority = order["priority"] if order is not None else "ROUTINE"
    signed_at = CLOCK.now_iso()
    bus_hours, cal_hours, breached = compute_turnaround(
        study["acquisition_completed_at"], signed_at, priority)
    report["signed_at"] = signed_at
    report["turnaround_business_hours"] = bus_hours
    report["turnaround_calendar_hours"] = cal_hours
    report["sla_breached"] = breached
    report["status"] = "SIGNED"
    touch(report)
    if study["status"] == "INTERPRETATION_IN_PROGRESS":
        study["status"] = "INTERPRETED"
        touch(study)
    return success_object(public(report))


@bp.post("/interpretation-reports/<interpretationReportId>/finalize")
def finalize_report(interpretationReportId):
    caller = authorized(["InterpretingPhysician"])
    report = require_path_resource("interpretation_reports", interpretationReportId)
    _check_author(caller, report)
    if report["status"] != "SIGNED":
        raise_error(ERR_REPORT_INVALID_STATE,
                    f"finalize requires SIGNED, found {report['status']}")
    report["status"] = "FINALIZED"
    report["finalized_at"] = CLOCK.now_iso()  # stamped at the first finalization
    touch(report)
    study = db["sleep_studies"].get(report["study_id"])
    if study is not None and study["status"] == "INTERPRETED":
        study["status"] = "REPORT_FINALIZED"
        touch(study)
    return success_object(public(report))


@bp.post("/interpretation-reports/<interpretationReportId>/open-addendum")
def open_addendum(interpretationReportId):
    caller = authorized(["InterpretingPhysician"])
    report = require_path_resource("interpretation_reports", interpretationReportId)
    _check_author(caller, report)
    if report["status"] != "FINALIZED":
        raise_error(ERR_REPORT_INVALID_STATE,
                    f"open-addendum requires FINALIZED, found {report['status']}")
    report["status"] = "ADDENDUM_OPEN"
    report["addendum_count"] = report.get("addendum_count", 0) + 1
    touch(report)
    return success_object(public(report))


@bp.post("/interpretation-reports/<interpretationReportId>/close-addendum")
def close_addendum(interpretationReportId):
    caller = authorized(["InterpretingPhysician"])
    report = require_path_resource("interpretation_reports", interpretationReportId)
    _check_author(caller, report)
    if report["status"] != "ADDENDUM_OPEN":
        raise_error(ERR_REPORT_INVALID_STATE,
                    f"close-addendum requires ADDENDUM_OPEN, found {report['status']}")
    report["status"] = "FINALIZED"
    touch(report)
    return success_object(public(report))
