"""Permit endpoints (PRD §3.6).

Lifecycle: APPLIED -> ISSUED -> INSPECTION_SCHEDULED -> PASSED / FAILED, with a
FAILED -> INSPECTION_SCHEDULED re-inspection edge.
"""
from flask import Blueprint, request

import db
import response
from errors import err
from helpers import (get_json_body, paginate, parse_pagination,
                     parse_datetime_field, require_enum, require_fields,
                     require_string, serialize, serialize_list, sort_by_created)
from middleware import get_identity, require_roles

bp = Blueprint("permits", __name__)

RESULTS = {"PASS", "FAIL"}


@bp.post("/v1/permits")
def file_permit():
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    body = get_json_body()
    require_fields(body, ["job_id", "jurisdiction", "permit_number"])

    job = db.service_jobs.get(body["job_id"])
    if job is None:
        raise err("ERR_NOT_FOUND", "Service job not found")
    require_string(body["jurisdiction"], "jurisdiction")
    require_string(body["permit_number"], "permit_number")

    record = {
        "job_id": job["id"],
        "jurisdiction": body["jurisdiction"],
        "permit_number": body["permit_number"],
        "status": "APPLIED",
        "inspection_at": None,
    }
    db.stamp_new(record)
    db.permits[record["id"]] = record
    return response.object_response(serialize(record), 201)


@bp.get("/v1/permits/<permit_id>")
def get_permit(permit_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Inspector"})
    record = db.permits.get(permit_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Permit not found")
    return response.object_response(serialize(record), 200)


@bp.get("/v1/permits")
def list_permits():
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Inspector"})
    limit, offset = parse_pagination()
    job_id = request.args.get("job_id")
    status = request.args.get("status")

    items = list(db.permits.values())
    if job_id is not None:
        items = [p for p in items if p["job_id"] == job_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return response.array_response(serialize_list(page), limit, offset, total, 200)


@bp.post("/v1/permits/<permit_id>/issue")
def issue_permit(permit_id):
    _, role = get_identity()
    require_roles(role, {"Inspector"})
    permit = db.permits.get(permit_id)
    if permit is None:
        raise err("ERR_NOT_FOUND", "Permit not found")
    if permit["status"] != "APPLIED":
        raise err("ERR_INVALID_STATE", "Permit must be APPLIED to issue")
    permit["status"] = "ISSUED"
    db.touch(permit)
    return response.object_response(serialize(permit), 200)


@bp.post("/v1/permits/<permit_id>/schedule-inspection")
def schedule_inspection(permit_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    permit = db.permits.get(permit_id)
    if permit is None:
        raise err("ERR_NOT_FOUND", "Permit not found")
    body = get_json_body()
    require_fields(body, ["inspection_at"])
    parse_datetime_field(body["inspection_at"], "inspection_at")

    # Schedulable from ISSUED (first inspection) or FAILED (re-inspection).
    if permit["status"] not in ("ISSUED", "FAILED"):
        raise err("ERR_INVALID_STATE", "Permit must be ISSUED or FAILED to schedule an inspection")

    permit["inspection_at"] = body["inspection_at"]
    permit["status"] = "INSPECTION_SCHEDULED"
    db.touch(permit)
    return response.object_response(serialize(permit), 200)


@bp.post("/v1/permits/<permit_id>/record-inspection")
def record_inspection(permit_id):
    _, role = get_identity()
    require_roles(role, {"Inspector"})
    permit = db.permits.get(permit_id)
    if permit is None:
        raise err("ERR_NOT_FOUND", "Permit not found")
    body = get_json_body()
    require_fields(body, ["result"])
    require_enum(body["result"], RESULTS, "result")

    if permit["status"] != "INSPECTION_SCHEDULED":
        raise err("ERR_INVALID_STATE", "Permit must be INSPECTION_SCHEDULED to record an inspection")

    permit["status"] = "PASSED" if body["result"] == "PASS" else "FAILED"
    db.touch(permit)
    return response.object_response(serialize(permit), 200)
