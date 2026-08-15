"""Quarterly reports, annoyance index, and the logical clock (PRD §3.9, §2.4)."""
from flask import Blueprint, request

from db import db, new_id
from errors import err
from middleware import get_caller, require_role, get_body
from response import success_object, success_list
from serialize import ser_report
import services
from services import touch
from util import now, iso, parse_quarter_label, quarter_bounds, set_now
from validate import validate, parse_pagination

bp = Blueprint("reports", __name__)

STAFF = ["NoiseOfficeAdmin", "NoiseAnalyst", "CommunityLiaison",
         "StudyCoordinator", "BoardMember"]


def _get_report(rid):
    r = db.reports.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", f"QuarterlyReport {rid} not found")
    return r


@bp.post("/quarterly-reports")
def create_report():
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("quarter_label", "quarter", True),
        ("notes", "str", False),
    ])
    require_role(caller, ["NoiseAnalyst"])
    for r in db.reports.values():
        if r["quarter_label"] == data["quarter_label"]:
            raise err("ERR_DUPLICATE_QUARTER_REPORT",
                      f"A report for {data['quarter_label']} already exists")
    year, q = parse_quarter_label(data["quarter_label"])
    start, end = quarter_bounds(year, q)
    snapshot = services.quarterly_rollup(year, q)
    t = now()
    r = {
        "id": new_id(),
        "quarter_label": data["quarter_label"],
        "period_start": start,
        "period_end": end,
        "status": "DRAFT",
        "notes": data.get("notes"),
        "created_by_user_id": caller.user_id,
        "approved_by_user_id": None,
        "published_at": None,
        "revision_round_count": 0,
        "created_at": t,
        "updated_at": t,
        "version": 1,
        **snapshot,
    }
    db.reports[r["id"]] = r
    return success_object(ser_report(r), status=201)


@bp.get("/quarterly-reports")
def list_reports():
    caller = get_caller()
    require_role(caller, STAFF)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = sorted(db.reports.values(), key=lambda r: r["created_at"])
    if status is not None:
        items = [r for r in items if r["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_report(r) for r in page], limit, offset, total)


@bp.get("/quarterly-reports/<reportId>")
def get_report(reportId):
    caller = get_caller()
    require_role(caller, STAFF)
    r = _get_report(reportId)
    return success_object(ser_report(r))


@bp.patch("/quarterly-reports/<reportId>")
def patch_report(reportId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("notes", "str", False),
        ("expected_report_version", "int", True),
    ])
    require_role(caller, ["NoiseAnalyst"])
    r = _get_report(reportId)
    if r["status"] != "DRAFT":
        raise err("ERR_INVALID_REPORT_STATE",
                  "Report notes are editable only while DRAFT")
    if data["expected_report_version"] != r["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_report_version does not match the report version")
    if "notes" in data:
        r["notes"] = data["notes"]
        touch(r)
    return success_object(ser_report(r))


@bp.post("/quarterly-reports/<reportId>/submit-for-review")
def submit_for_review(reportId):
    caller = get_caller()
    get_body()
    require_role(caller, ["NoiseAnalyst"])
    r = _get_report(reportId)
    if r["status"] != "DRAFT":
        raise err("ERR_INVALID_REPORT_STATE",
                  "submit-for-review requires status DRAFT")
    if r["period_end"] > now():
        raise err("ERR_QUARTER_NOT_CLOSED",
                  "The reporting period has not fully closed")
    for e in db.events.values():
        if (r["period_start"] <= e["started_at"] < r["period_end"]
                and e["status"] in ("CAPTURED", "SCREENING")):
            raise err("ERR_UNCLASSIFIED_EVENTS_REMAIN",
                      "Unclassified events remain in the reporting period")
    r["status"] = "UNDER_REVIEW"
    touch(r)
    return success_object(ser_report(r))


@bp.post("/quarterly-reports/<reportId>/approve")
def approve_report(reportId):
    caller = get_caller()
    get_body()
    require_role(caller, ["BoardMember"])
    r = _get_report(reportId)
    # segregation of duties precedes the state check (validation gate 5)
    if caller.user_id == r["created_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "The approver must differ from the report creator")
    if r["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_REPORT_STATE",
                  "approve requires status UNDER_REVIEW")
    r["status"] = "APPROVED"
    r["approved_by_user_id"] = caller.user_id
    touch(r)
    return success_object(ser_report(r))


@bp.post("/quarterly-reports/<reportId>/return-for-revision")
def return_for_revision(reportId):
    caller = get_caller()
    body = get_body()
    validate(body, [("reason", "str", True)])
    require_role(caller, ["BoardMember"])
    r = _get_report(reportId)
    if r["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_REPORT_STATE",
                  "return-for-revision requires status UNDER_REVIEW")
    r["status"] = "DRAFT"
    r["revision_round_count"] += 1
    touch(r)
    return success_object(ser_report(r))


@bp.post("/quarterly-reports/<reportId>/publish")
def publish_report(reportId):
    caller = get_caller()
    get_body()
    require_role(caller, ["NoiseOfficeAdmin"])
    r = _get_report(reportId)
    if r["status"] != "APPROVED":
        raise err("ERR_INVALID_REPORT_STATE", "publish requires status APPROVED")
    r["status"] = "PUBLISHED"
    r["published_at"] = now()
    touch(r)
    return success_object(ser_report(r))


# ------------------------- computed reads + clock ---------------------------

@bp.get("/community-zones/<zoneCode>/annoyance-index")
def get_annoyance(zoneCode):
    caller = get_caller()
    require_role(caller, STAFF)
    return success_object(services.annoyance_index(zoneCode))


@bp.post("/_clock/set_current_utc", strict_slashes=False)
def set_clock():
    caller = get_caller()
    body = get_body()
    data = validate(body, [("to_iso8601", "dt", True)])
    require_role(caller, ["NoiseOfficeAdmin"])
    set_now(data["to_iso8601"])
    # the clock advance fires exactly one sweep: overdue notification escalation
    services.sweep_notifications_globally()
    return success_object({"current_utc": iso(now())})


@bp.get("/_clock/current_utc", strict_slashes=False)
def get_clock():
    caller = get_caller()
    require_role(caller, STAFF + ["OperatorRep", "Complainant"])
    return success_object({"current_utc": iso(now())})
