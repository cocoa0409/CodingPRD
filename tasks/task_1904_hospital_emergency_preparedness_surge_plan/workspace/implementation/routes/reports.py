"""Coalition coordination and regulatory reporting."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, g, request

from db import clock, store
from domain import (AUDIENCES, REPORT_DUE_OFFSET_HOURS, REPORT_TYPES, get_or_404,
                    list_response, ser_report)
from envelope import success
from errors import ApiError
from security import ALL_ROLES, authorize
from util import field_dt, field_enum, field_str, new_entity, require_body, touch

bp = Blueprint("reports", __name__)


@bp.post("/external-reports")
@authorize(["LiaisonOfficer"])
def create_report():
    body = require_body()
    audience = field_enum(body, "audience", AUDIENCES, required=True)
    report_type = field_enum(body, "report_type", REPORT_TYPES, required=True)
    period_start = field_dt(body, "period_start", required=True)
    period_end = field_dt(body, "period_end", required=True)
    body_summary = field_str(body, "body_summary", required=True)
    incident_id = field_str(body, "incident_id")

    if incident_id is not None:
        get_or_404("incidents", incident_id)

    due_at = period_end + timedelta(hours=REPORT_DUE_OFFSET_HOURS[report_type])

    report = new_entity()
    report.update({
        "audience": audience,
        "report_type": report_type,
        "incident_id": incident_id,
        "period_start": period_start,
        "period_end": period_end,
        "body_summary": body_summary,
        "due_at": due_at,
        "status": "DRAFT",
        "created_by_id": g.user_id,
        "submitted_at": None,
        "submitted_late": None,
        "hours_late": None,
    })
    store["reports"][report["id"]] = report
    return success(ser_report(report), "object", 201)


@bp.get("/external-reports")
@authorize(ALL_ROLES)
def list_reports():
    incident_id = request.args.get("incident_id")
    audience = request.args.get("audience")
    report_type = request.args.get("report_type")
    status = request.args.get("status")

    def predicate(r):
        if incident_id is not None and r["incident_id"] != incident_id:
            return False
        if audience is not None and r["audience"] != audience:
            return False
        if report_type is not None and r["report_type"] != report_type:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    return list_response("reports", ser_report, predicate)


@bp.get("/external-reports/<report_id>")
@authorize(ALL_ROLES)
def get_report(report_id):
    return success(ser_report(get_or_404("reports", report_id)), "object", 200)


@bp.post("/external-reports/<report_id>/submit")
@authorize(["LiaisonOfficer", "HospitalAdministrator"])
def submit_report(report_id):
    report = get_or_404("reports", report_id)

    # Segregation of duties (priority 6) precedes the state guard (priority 8).
    if g.user_id == report["created_by_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "the submitter may not be the report's creator")
    if report["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a DRAFT report can be submitted")

    submitted_at = clock.now()
    report["status"] = "SUBMITTED"
    report["submitted_at"] = submitted_at
    # Late filings are accepted and flagged, never rejected.
    report["submitted_late"] = submitted_at > report["due_at"]
    seconds = max(0, int((submitted_at - report["due_at"]).total_seconds()))
    report["hours_late"] = (Decimal(seconds) / Decimal(3600)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    touch(report)
    return success(ser_report(report), "object", 200)
