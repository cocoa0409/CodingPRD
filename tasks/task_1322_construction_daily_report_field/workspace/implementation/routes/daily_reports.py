"""DailyReport: create/read/list, OCC header edit, lifecycle transitions."""
from flask import Blueprint, request

from auth import ctx, need
from calc import bump_report, touch
from clock import clock
from db import store
from envelope import success
from errors import ApiError, bad
from route_helpers import stamp, list_response
from serializers import ser_report
from util import parse_date
from validate import (
    body,
    req_str,
    opt_str,
    opt_dt,
    opt_bool,
    req_date,
    req_int,
)

bp = Blueprint("daily_reports", __name__)

REPORT_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "APPROVED",
    "REVISION_REQUESTED",
    "LOCKED",
)
RETENTION_CLASSES = ("STANDARD", "CLAIMS_HOLD")


def get_report(rid):
    r = store.daily_reports.get(rid)
    if r is None:
        raise ApiError("ERR_REPORT_NOT_FOUND", 404, "DailyReport not found")
    return r


def require_editable(report):
    from calc import content_posture

    if content_posture(report) != "EDITABLE":
        raise ApiError(
            "ERR_REPORT_NOT_EDITABLE", 409, "Parent report is SEALED"
        )


@bp.post("/daily-reports")
def create_report():
    _, role = ctx()
    need(role, ["Superintendent"])
    b = body()
    project_id = req_str(b, "project_id")
    report_date = req_date(b, "report_date")
    general_notes = opt_str(b, "general_notes")
    shift_start = opt_dt(b, "shift_start_actual")
    shift_end = opt_dt(b, "shift_end_actual")
    no_work = opt_bool(b, "no_work_performed", False)
    # body FK existence (priority 5)
    if project_id not in store.projects:
        raise ApiError("ERR_PROJECT_NOT_FOUND", 404, "Project not found")
    # uniqueness (8.2): one report per (project_id, report_date)
    for r in store.daily_reports.values():
        if r["project_id"] == project_id and r["report_date"] == report_date:
            raise ApiError(
                "ERR_DUPLICATE_REPORT_DATE",
                409,
                "A report already exists for this project and date",
            )
    rec = stamp(
        {
            "project_id": project_id,
            "report_date": report_date,
            "general_notes": general_notes,
            "shift_start_actual": shift_start,
            "shift_end_actual": shift_end,
            "no_work_performed": no_work,
            "status": "DRAFT",
            "submitted_by_user_id": None,
            "submitted_at": None,
            "revision_count": 0,
        }
    )
    store.daily_reports[rec["id"]] = rec
    return success(ser_report(rec), 201)


@bp.get("/daily-reports/<rid>")
def get_one_report(rid):
    ctx()
    return success(ser_report(get_report(rid)), 200)


@bp.get("/daily-reports")
def list_reports():
    ctx()
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    date_from = request.args.get("report_date_from")
    date_to = request.args.get("report_date_to")
    retention_class = request.args.get("retention_class")
    if status is not None and status not in REPORT_STATUSES:
        bad("Invalid status filter")
    if retention_class is not None and retention_class not in RETENTION_CLASSES:
        bad("Invalid retention_class filter")
    d_from = parse_date(date_from) if date_from is not None else None
    if date_from is not None and d_from is None:
        bad("Invalid report_date_from")
    d_to = parse_date(date_to) if date_to is not None else None
    if date_to is not None and d_to is None:
        bad("Invalid report_date_to")
    rows = list(store.daily_reports.values())
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if d_from is not None:
        rows = [r for r in rows if r["report_date"] >= d_from]
    if d_to is not None:
        rows = [r for r in rows if r["report_date"] <= d_to]
    if retention_class is not None:
        from calc import report_incident_flags

        rows = [
            r
            for r in rows
            if report_incident_flags(r["id"])[1] == retention_class
        ]
    return list_response(rows, ser_report)


@bp.put("/daily-reports/<rid>")
def edit_report(rid):
    _, role = ctx()
    need(role, ["Superintendent"])
    r = get_report(rid)
    b = body()
    expected = req_int(b, "expected_report_version")
    # shape validation of editable fields
    general_notes = opt_str(b, "general_notes", None)
    shift_start = opt_dt(b, "shift_start_actual", None)
    shift_end = opt_dt(b, "shift_end_actual", None)
    no_work = opt_bool(b, "no_work_performed", None)
    # priority 6.1: posture gate
    require_editable(r)
    # priority 6.5: OCC
    if expected != r["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Report version is stale")
    if "general_notes" in b:
        r["general_notes"] = general_notes
    if "shift_start_actual" in b:
        r["shift_start_actual"] = shift_start
    if "shift_end_actual" in b:
        r["shift_end_actual"] = shift_end
    if "no_work_performed" in b and no_work is not None:
        r["no_work_performed"] = no_work
    touch(r)
    return success(ser_report(r), 200)


@bp.post("/daily-reports/<rid>/submit")
def submit_report(rid):
    uid, role = ctx()
    need(role, ["Superintendent"])
    r = get_report(rid)
    # priority 6: own state machine
    if r["status"] != "DRAFT":
        raise ApiError(
            "ERR_REPORT_INVALID_TRANSITION", 409, "Report must be DRAFT to submit"
        )
    # priority 9: temporal
    if r["report_date"] > clock.now().date():
        raise ApiError(
            "ERR_REPORT_DATE_FUTURE", 422, "report_date is after the current date"
        )
    # priority 10.3: submit content gates
    has_weather = any(
        w["report_id"] == r["id"] for w in store.weather_observations.values()
    )
    if not has_weather:
        raise ApiError(
            "ERR_WEATHER_MISSING", 409, "At least one weather observation is required"
        )
    active_crew = any(
        c["report_id"] == r["id"] and c["status"] == "ACTIVE"
        for c in store.crew_entries.values()
    )
    if not active_crew and not r["no_work_performed"]:
        raise ApiError(
            "ERR_NO_WORK_RECORDED",
            409,
            "No ACTIVE crew entries and no_work_performed is false",
        )
    if r["no_work_performed"] and active_crew:
        raise ApiError(
            "ERR_WORK_ENTRIES_CONFLICT",
            409,
            "no_work_performed is true but ACTIVE crew entries exist",
        )
    for d in store.material_deliveries.values():
        if d["report_id"] == r["id"] and d["status"] != "INSPECTED":
            raise ApiError(
                "ERR_DELIVERY_NOT_INSPECTED",
                409,
                "All deliveries must be INSPECTED before submit",
            )
    for ev in store.delay_events.values():
        if ev["report_id"] == r["id"] and ev["status"] == "RECORDED":
            raise ApiError(
                "ERR_DELAY_EVENT_UNCLASSIFIED",
                409,
                "Delay events must be classified before submit",
            )
    # priority 10.6: project must be ACTIVE
    project = store.projects.get(r["project_id"])
    if project["status"] != "ACTIVE":
        raise ApiError(
            "ERR_PROJECT_NOT_ACTIVE", 409, "Project must be ACTIVE to submit"
        )
    r["status"] = "SUBMITTED"
    r["submitted_by_user_id"] = uid
    r["submitted_at"] = clock.now()
    touch(r)
    return success(ser_report(r), 200)


def _report_transition(rid, roles, from_states, to_state, mutate=None):
    uid, role = ctx()
    need(role, roles)
    r = get_report(rid)
    if r["status"] not in from_states:
        raise ApiError(
            "ERR_REPORT_INVALID_TRANSITION",
            409,
            "Report status does not allow this transition",
        )
    if mutate is not None:
        mutate(r, uid)
    r["status"] = to_state
    touch(r)
    return success(ser_report(r), 200)


@bp.post("/daily-reports/<rid>/start-review")
def start_review(rid):
    return _report_transition(rid, ["ProjectManager"], ("SUBMITTED",), "UNDER_REVIEW")


@bp.post("/daily-reports/<rid>/approve")
def approve_report(rid):
    uid, role = ctx()
    need(role, ["ProjectManager"])
    r = get_report(rid)
    if r["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_REPORT_INVALID_TRANSITION", 409, "Report must be UNDER_REVIEW"
        )
    # priority 8: segregation of duties vs submitter
    if uid == r["submitted_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", 403, "Approver must differ from submitter"
        )
    # rollup cascade is derived at read time from report status + ACTIVE entries
    r["status"] = "APPROVED"
    touch(r)
    return success(ser_report(r), 200)


@bp.post("/daily-reports/<rid>/request-revision")
def request_revision(rid):
    _, role = ctx()
    need(role, ["ProjectManager"])
    r = get_report(rid)
    b = body()
    req_str(b, "reason")
    if r["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_REPORT_INVALID_TRANSITION", 409, "Report must be UNDER_REVIEW"
        )
    r["status"] = "REVISION_REQUESTED"
    r["revision_count"] += 1
    touch(r)
    return success(ser_report(r), 200)


@bp.post("/daily-reports/<rid>/return-to-draft")
def return_to_draft(rid):
    return _report_transition(
        rid, ["Superintendent"], ("REVISION_REQUESTED",), "DRAFT"
    )


@bp.post("/daily-reports/<rid>/recall")
def recall_report(rid):
    uid, role = ctx()
    need(role, ["Superintendent"])
    r = get_report(rid)
    if r["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_REPORT_INVALID_TRANSITION", 409, "Report must be SUBMITTED"
        )
    if uid != r["submitted_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", 403, "Only the original submitter may recall"
        )
    r["status"] = "DRAFT"
    touch(r)
    return success(ser_report(r), 200)


@bp.post("/daily-reports/<rid>/reopen")
def reopen_report(rid):
    _, role = ctx()
    need(role, ["ProjectManager"])
    r = get_report(rid)
    b = body()
    req_str(b, "reason")
    if r["status"] != "APPROVED":
        raise ApiError(
            "ERR_REPORT_INVALID_TRANSITION", 409, "Report must be APPROVED"
        )
    # compensating rollup is derived at read time from report status
    r["status"] = "UNDER_REVIEW"
    touch(r)
    return success(ser_report(r), 200)


@bp.post("/daily-reports/<rid>/lock")
def lock_report(rid):
    _, role = ctx()
    need(role, ["SystemAdmin"])
    r = get_report(rid)
    if r["status"] != "APPROVED":
        raise ApiError(
            "ERR_REPORT_INVALID_TRANSITION", 409, "Report must be APPROVED to lock"
        )
    r["status"] = "LOCKED"
    touch(r)
    return success(ser_report(r), 200)
