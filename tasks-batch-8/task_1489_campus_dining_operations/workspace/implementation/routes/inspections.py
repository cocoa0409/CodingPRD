"""InspectionReport and CorrectiveAction endpoints."""
from flask import Blueprint

from db import DB, new_id, next_seq
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok
from services import (
    SEVERITIES,
    c5_score,
    ca_due_date,
    get_action,
    get_hall,
    get_report,
    ser,
    stamp,
    suspend_hall,
    touch,
)
from util import as_enum, as_iso_date, as_list, as_str, body, required
from routes.common import list_endpoint

bp = Blueprint("inspections", __name__)


def _validate_violations(violations):
    as_list(violations, "violations")
    for v in violations:
        if not isinstance(v, dict):
            raise ApiError("ERR_VALIDATION", 400, "Each violation must be an object")
        as_str(required(v, "code"), "violations[].code")
        as_enum(required(v, "severity"), "violations[].severity", SEVERITIES)
    return [{"code": v["code"], "severity": v["severity"]} for v in violations]


@bp.post("/inspection-reports")
def create_report():
    user_id, _ = auth(["HealthInspector"])
    data = body()
    dining_hall_id = required(data, "dining_hall_id")
    if isinstance(dining_hall_id, str):
        get_hall(dining_hall_id)
    inspection_date = as_iso_date(required(data, "inspection_date"), "inspection_date")
    violations = _validate_violations(required(data, "violations"))
    if not isinstance(dining_hall_id, str):
        raise ApiError("ERR_VALIDATION", 400, "dining_hall_id must be a string")
    rec = {
        "id": new_id(),
        "dining_hall_id": dining_hall_id,
        "inspector_user_id": user_id,
        "inspection_date": inspection_date,
        "violations": violations,
        "score": None,
        "outcome": None,
        "status": "DRAFT",
        "_seq": next_seq(),
    }
    stamp(rec)
    DB["inspection_reports"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@bp.get("/inspection-reports")
def list_reports():
    return list_endpoint(
        "inspection_reports",
        [
            ("dining_hall_id", "dining_hall_id"),
            ("status", "status"),
            ("outcome", "outcome"),
        ],
    )


@bp.get("/inspection-reports/<rid>")
def get_one_report(rid):
    auth(ALL_ROLES)
    return ok(ser(get_report(rid)))


def _create_action(report, violation_code, severity, due_date):
    rec = {
        "id": new_id(),
        "inspection_report_id": report["id"],
        "violation_code": violation_code,
        "severity": severity,
        "due_date": due_date,
        "status": "OPEN",
        "resolved_by_user_id": None,
        "verified_by_user_id": None,
        "_seq": next_seq(),
    }
    stamp(rec)
    DB["corrective_actions"][rec["id"]] = rec
    return rec


@bp.post("/inspection-reports/<rid>/submit")
def submit_report(rid):
    auth(["HealthInspector"])
    report = get_report(rid)
    if report["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Report is not DRAFT")
    score, outcome = c5_score(report["violations"])
    report["score"] = score
    report["outcome"] = outcome
    report["status"] = "SUBMITTED"
    for v in report["violations"]:
        _create_action(report, v["code"], v["severity"], ca_due_date(report["inspection_date"], v["severity"]))
    if outcome == "FAIL":
        hall = get_hall(report["dining_hall_id"])
        suspend_hall(hall)
    touch(report)
    return ok(ser(report))


@bp.post("/inspection-reports/<rid>/acknowledge")
def acknowledge_report(rid):
    auth(["HallManager"])
    report = get_report(rid)
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report is not SUBMITTED")
    report["status"] = "ACKNOWLEDGED"
    touch(report)
    return ok(ser(report))


@bp.post("/inspection-reports/<rid>/close")
def close_report(rid):
    auth(["HealthInspector"])
    report = get_report(rid)
    if report["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report is not ACKNOWLEDGED")
    for action in DB["corrective_actions"].values():
        if action["inspection_report_id"] == rid and action["status"] != "VERIFIED":
            raise ApiError(
                "ERR_INSPECTION_INCOMPLETE",
                409,
                "Every corrective action must be VERIFIED before close",
            )
    report["status"] = "CLOSED"
    touch(report)
    return ok(ser(report))


@bp.post("/inspection-reports/<rid>/corrective-actions")
def add_action(rid):
    auth(["HealthInspector"])
    report = get_report(rid)
    if report["status"] not in ("SUBMITTED", "ACKNOWLEDGED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Report is not SUBMITTED or ACKNOWLEDGED"
        )
    data = body()
    violation_code = as_str(required(data, "violation_code"), "violation_code")
    severity = as_enum(required(data, "severity"), "severity", SEVERITIES)
    due_date = as_iso_date(required(data, "due_date"), "due_date")
    rec = _create_action(report, violation_code, severity, due_date)
    return ok(ser(rec), status=201)


@bp.get("/corrective-actions")
def list_actions():
    return list_endpoint(
        "corrective_actions",
        [
            ("inspection_report_id", "inspection_report_id"),
            ("status", "status"),
            ("severity", "severity"),
        ],
    )


@bp.get("/corrective-actions/<aid>")
def get_one_action(aid):
    auth(ALL_ROLES)
    return ok(ser(get_action(aid)))


@bp.post("/corrective-actions/<aid>/resolve")
def resolve_action(aid):
    user_id, _ = auth(["HallManager"])
    action = get_action(aid)
    if action["status"] not in ("OPEN", "OVERDUE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Action is not OPEN or OVERDUE")
    report = get_report(action["inspection_report_id"])
    if report["status"] not in ("SUBMITTED", "ACKNOWLEDGED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Report is not SUBMITTED or ACKNOWLEDGED"
        )
    action["resolved_by_user_id"] = user_id
    action["status"] = "RESOLVED"
    touch(action)
    return ok(ser(action))


@bp.post("/corrective-actions/<aid>/verify")
def verify_action(aid):
    user_id, _ = auth(["HealthInspector"])
    action = get_action(aid)
    if action["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Action is not RESOLVED")
    report = get_report(action["inspection_report_id"])
    if report["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report is not ACKNOWLEDGED")
    action["verified_by_user_id"] = user_id
    action["status"] = "VERIFIED"
    touch(action)
    return ok(ser(action))


@bp.post("/corrective-actions/<aid>/reopen")
def reopen_action(aid):
    auth(["HealthInspector"])
    action = get_action(aid)
    if action["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Action is not RESOLVED")
    action["resolved_by_user_id"] = None
    action["status"] = "OPEN"
    if action["severity"] == "CRITICAL":
        report = get_report(action["inspection_report_id"])
        hall = get_hall(report["dining_hall_id"])
        suspend_hall(hall)
    touch(action)
    return ok(ser(action))
