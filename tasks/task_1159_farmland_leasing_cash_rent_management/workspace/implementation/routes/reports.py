from flask import Blueprint, request
from middleware import get_caller, require_role, get_json_body
from services.common import require_string, require_enum, require_datetime, parse_pagination
from response import success_object, success_list
from errors import ApiError
from db import db, touch, CLOCK, add_days
from services.serialize import serialize
from services.sweeps import create_report

bp = Blueprint("reports", __name__)
READ_ROLES = {"FarmManager", "Landlord", "Tenant"}
REPORT_TYPES = {"QUARTERLY", "ANNUAL", "SETTLEMENT", "TERMINATION"}


@bp.route("/reports", methods=["POST"])
def create_owner_report():
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    body = get_json_body()
    landlord_id = require_string(body, "landlord_id")
    report_type = require_enum(body, "report_type", REPORT_TYPES)
    period_start = require_datetime(body, "period_start")
    period_end = require_datetime(body, "period_end")

    if landlord_id not in db.landlords:
        raise ApiError("ERR_NOT_FOUND", 404, f"Landlord {landlord_id} not found")

    if period_start > period_end:
        raise ApiError("ERR_INVALID_PERIOD", 422,
                       "period_start must be on or before period_end")

    # Closed-interval overlap with existing reports for the same landlord
    for r in db.reports.values():
        if r["landlord_id"] != landlord_id:
            continue
        # closed interval overlap: start <= other.end AND other.start <= end
        if period_start <= r["period_end"] and r["period_start"] <= period_end:
            raise ApiError("ERR_REPORT_PERIOD_OVERLAP", 409,
                           "Report period overlaps an existing report for this landlord")

    rec = create_report(landlord_id, report_type, period_start, period_end)
    return success_object(serialize("report", rec), status=201)


@bp.route("/reports/<reportId>", methods=["GET"])
def get_report(reportId):
    _, role = get_caller()
    require_role(role, READ_ROLES)
    rec = db.reports.get(reportId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Report {reportId} not found")
    return success_object(serialize("report", rec))


@bp.route("/reports", methods=["GET"])
def list_reports():
    _, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(db.reports.values(), key=lambda r: r["created_at"])
    landlord_q = request.args.get("landlord_id")
    if landlord_q is not None:
        items = [r for r in items if r["landlord_id"] == landlord_q]
    status_q = request.args.get("status")
    if status_q is not None:
        items = [r for r in items if r["status"] == status_q]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize("report", r) for r in page], limit, offset, total)


@bp.route("/reports/<reportId>/send", methods=["POST"])
def send_report(reportId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.reports.get(reportId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Report {reportId} not found")
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Report in state {rec['status']} cannot be sent")
    landlord = db.landlords.get(rec["landlord_id"])
    ack_days = landlord.get("ack_required_days", 14) if landlord else 14
    rec["status"] = "SENT"
    rec["sent_at"] = CLOCK.get()
    rec["ack_due_date"] = add_days(rec["sent_at"], ack_days)
    touch(rec)
    return success_object(serialize("report", rec))


@bp.route("/reports/<reportId>/acknowledge", methods=["POST"])
def acknowledge_report(reportId):
    user_id, role = get_caller()
    require_role(role, {"Landlord"})
    rec = db.reports.get(reportId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Report {reportId} not found")
    if rec["landlord_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the report recipient")
    if rec["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Report in state {rec['status']} cannot be acknowledged")
    rec["status"] = "ACKNOWLEDGED"
    rec["acknowledged_at"] = CLOCK.get()
    rec["escalation_required"] = False
    touch(rec)
    return success_object(serialize("report", rec))
