"""Monthly technical-dispatch-reliability reporting (PRD 3.8)."""

from flask import Blueprint, request

from db import db, new_row, touch, public
from errors import ApiError, bad_request
from middleware import (
    require, check_ownership, scope_for_lessee,
    LESSOR_OPS, LESSEE, MAINTENANCE_CONTROLLER, BILLING_ADMIN,
)
from response import object_response, pagination, paged
from routes.common import find_aircraft, find_lease, find_report, filtered
from services import calculations as C
from services import workflows as W
import validate as V

bp = Blueprint("reliability", __name__)

REPORTABLE_LEASE_STATUSES = ("ACTIVE", "SUSPENDED", "TERMINATING")


@bp.post("/wetlease/reliability-reports")
def create_report():
    require((MAINTENANCE_CONTROLLER,))
    body = V.json_body()
    lease_id = V.req_str(body, "lease_id")
    aircraft_id = V.req_str(body, "aircraft_id")
    period_month = V.req_month(body, "period_month")

    find_aircraft(aircraft_id)
    lease = find_lease(lease_id)

    if lease["status"] not in REPORTABLE_LEASE_STATUSES:
        raise ApiError("ERR_LEASE_INVALID_STATE")

    for existing in db.reliability_reports.values():
        if (existing["lease_id"] == lease_id
                and existing["aircraft_id"] == aircraft_id
                and existing["period_month"] == period_month
                and existing["status"] != "REJECTED"):
            raise bad_request(
                "a report for this lease, airframe and period_month already exists")

    legs = [leg for leg in W.legs_of_lease(lease_id)
            if leg["aircraft_id"] == aircraft_id
            and C.month_of(leg["_scheduled_out"]) == period_month]
    metrics = C.technical_dispatch_reliability(lease, legs)

    row = new_row()
    row.update({
        "lease_id": lease_id,
        "aircraft_id": aircraft_id,
        "period_month": period_month,
        "status": "SUBMITTED",
        "review_note": None,
    })
    row.update(metrics)
    db.reliability_reports[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/wetlease/reliability-reports/<report_id>")
def get_report(report_id):
    actor = require((MAINTENANCE_CONTROLLER, BILLING_ADMIN, LESSOR_OPS, LESSEE))
    report = find_report(report_id)
    check_ownership(actor, "report", report)
    return object_response(public(report))


@bp.get("/wetlease/reliability-reports")
def list_reports():
    actor = require((MAINTENANCE_CONTROLLER, BILLING_ADMIN, LESSOR_OPS, LESSEE))
    limit, offset = pagination(request.args)
    rows = filtered(list(db.reliability_reports.values()), request.args, {
        "lease_id": "lease_id",
        "aircraft_id": "aircraft_id",
        "period_month": "period_month",
        "status": "status",
    })
    rows = scope_for_lessee(actor, "report", rows)
    return paged(rows, limit, offset)


@bp.post("/wetlease/reliability-reports/<report_id>/review")
def review_report(report_id):
    actor = require((LESSEE,))
    body = V.json_body()
    decision = V.req_enum(body, "decision", ("ACCEPT", "REJECT"))
    review_note = V.opt_str(body, "review_note")
    report = find_report(report_id)
    check_ownership(actor, "report", report)

    if report["status"] != "SUBMITTED":
        raise bad_request("only a SUBMITTED report may be reviewed")

    report["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    if review_note is not None:
        report["review_note"] = review_note
    touch(report)
    return object_response(public(report))
