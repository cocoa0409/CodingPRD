"""Resident complaints, SLA clocks, triage and closure (PRD 3.10)."""
from datetime import timedelta

from flask import Blueprint

import calc
import clock
import db
import response
import validators as v
from errors import ApiError
from middleware import endpoint
from services import derive

bp = Blueprint("service_requests", __name__)

COMPLAINT_TYPES = ("POTHOLE", "CRACKING", "PONDING", "UTILITY_CUT_SETTLEMENT")
SEVERITIES = ("LOW", "MEDIUM", "HIGH")
DISPOSITIONS = ("PATCH", "DEFER_TO_CAPITAL")
CLOSURE_CODES = ("PATCHED", "DUPLICATE")
CLOSED_STATES = ("CLOSED_PATCHED", "CLOSED_DUPLICATE", "CLOSED_BY_CAPITAL")
READ_ROLES = ("PavementEngineer", "BudgetOfficer", "Inspector", "Resident")


def _find_request(request_id):
    row = db.service_requests.get(request_id)
    if row is None:
        raise ApiError("ERR_SERVICE_REQUEST_NOT_FOUND")
    return row


@bp.post("/service-requests")
@endpoint("Resident", "PavementEngineer")
def create_request():
    data = v.body()
    segment_id = v.field_id(data, "segment_id")
    complaint_type = v.field_enum(data, "complaint_type", COMPLAINT_TYPES)
    severity = v.field_enum(data, "reported_severity", SEVERITIES)
    location_note = v.field_string(data, "location_note", 1, 200)

    segment = db.segments.get(segment_id)
    if segment is None:
        raise ApiError("ERR_SEGMENT_NOT_FOUND")

    row = {
        "id": db.new_id(),
        "segment_id": segment_id,
        "complaint_type": complaint_type,
        "reported_severity": severity,
        "location_note": location_note,
        "request_status": "NEW",
        "capital_project_id": None,
        "triaged_at": None,
        "closed_at": None,
        "closure_code": None,
        "sla_due_at": None,
        "sla_breached": False,
    }
    row.update(db.audit())
    # The service clock starts at creation, off the logical clock.
    row["sla_due_at"] = row["created_at"] + timedelta(
        hours=calc.SLA_HOURS[severity]
    )
    row["sla_breached"] = derive.request_sla_breached(row)
    db.service_requests[row["id"]] = row
    derive.recompute_segment_counters(segment)
    return response.object_response(row, 201)


@bp.get("/service-requests/<request_id>")
@endpoint(*READ_ROLES)
def read_request(request_id):
    row = _find_request(request_id)
    return response.object_response(derive.refresh_request_breach(row))


@bp.get("/service-requests")
@endpoint(*READ_ROLES)
def list_requests():
    rows = db.ordered(db.service_requests.values())
    for row in rows:
        derive.refresh_request_breach(row)
    rows = v.filter_rows(rows, {
        "segment_id": "segment_id",
        "capital_project_id": "capital_project_id",
        "request_status": "request_status",
        "reported_severity": "reported_severity",
    })
    page, meta = v.paginate(rows)
    return response.array_response(page, pagination=meta)


@bp.post("/service-requests/<request_id>/triage")
@endpoint("PavementEngineer")
def triage_request(request_id):
    data = v.body()
    disposition = v.field_enum(data, "disposition", DISPOSITIONS)
    target_project_id = v.field_id(
        data, "target_project_id",
        required=(disposition == "DEFER_TO_CAPITAL"),
    )

    row = _find_request(request_id)
    target = None
    if disposition == "DEFER_TO_CAPITAL":
        target = db.projects.get(target_project_id)
        if target is None:
            raise ApiError("ERR_PROJECT_NOT_FOUND")

    if row["request_status"] != "NEW":
        raise ApiError("ERR_SERVICE_REQUEST_NOT_NEW")

    if disposition == "PATCH":
        derive.apply_updates(row, {
            "request_status": "TRIAGED_PATCH",
            "triaged_at": clock.now(),
        })
    else:
        eligible = target["delivery_status"] != "ACCEPTED" and any(
            l["segment_id"] == row["segment_id"]
            for l in derive.active_lines_of_project(target["id"])
        )
        if not eligible:
            raise ApiError("ERR_TARGET_PROJECT_NOT_ELIGIBLE")
        derive.apply_updates(row, {
            "request_status": "DEFERRED_TO_CAPITAL",
            "triaged_at": clock.now(),
            "capital_project_id": target["id"],
        })
    # Triage never moves the segment's open complaint counter (PRD 2.11).
    return response.object_response(derive.refresh_request_breach(row))


@bp.post("/service-requests/<request_id>/close")
@endpoint("PavementEngineer")
def close_request(request_id):
    data = v.body()
    closure_code = v.field_enum(data, "closure_code", CLOSURE_CODES)

    row = _find_request(request_id)
    if row["request_status"] in CLOSED_STATES:
        raise ApiError("ERR_SERVICE_REQUEST_ALREADY_CLOSED")
    if closure_code == "PATCHED" and row["request_status"] != "TRIAGED_PATCH":
        raise ApiError("ERR_SERVICE_REQUEST_NOT_TRIAGED")

    now = clock.now()
    derive.apply_updates(row, {
        "request_status": "CLOSED_PATCHED" if closure_code == "PATCHED"
        else "CLOSED_DUPLICATE",
        "closure_code": closure_code,
        "closed_at": now,
    })
    derive.apply_updates(row, {"sla_breached": derive.request_sla_breached(row)})
    segment = db.segments.get(row["segment_id"])
    if segment is not None:
        derive.recompute_segment_counters(segment)
    return response.object_response(row)
