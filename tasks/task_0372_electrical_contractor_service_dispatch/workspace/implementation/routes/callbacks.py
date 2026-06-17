"""Callback (warranty) endpoints (PRD §3.8).

Filing computes covered_by_warranty = (current_utc <= job.warranty_until). A
covered callback opens OPEN and reopens the job (INVOICED/CLOSED -> WARRANTY);
an uncovered callback is rejected with ERR_NOT_WARRANTY_COVERED. Resolution
moves OPEN -> RESOLVED once the job is back in COMPLETED or INVOICED.
"""
from flask import Blueprint, request

import clock
import db
import response
from errors import err
from helpers import (get_json_body, paginate, parse_pagination, require_fields,
                     require_string, serialize, serialize_list, sort_by_created)
from middleware import get_identity, require_roles

bp = Blueprint("callbacks", __name__)


@bp.post("/v1/callbacks")
def file_callback():
    user_id, role = get_identity()
    require_roles(role, {"Customer", "Dispatcher"})
    body = get_json_body()
    require_fields(body, ["job_id", "reason"])

    job = db.service_jobs.get(body["job_id"])
    if job is None:
        raise err("ERR_NOT_FOUND", "Service job not found")

    # Ownership: a Customer may file only against their own job.
    if role == "Customer" and job["customer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Customers may only file callbacks on their own job")

    require_string(body["reason"], "reason")

    # State legality (PRD §2.6): the WARRANTY reopen is defined only from
    # INVOICED or CLOSED.
    if job["status"] not in ("INVOICED", "CLOSED"):
        raise err("ERR_INVALID_STATE", "Callbacks may only be filed against an invoiced or closed job")

    # Warranty coverage business check.
    warranty_until = job.get("warranty_until")
    covered = False
    if warranty_until is not None:
        covered = clock.now() <= clock.parse_iso(warranty_until)
    if not covered:
        raise err("ERR_NOT_WARRANTY_COVERED", "Callback filed after the warranty window has elapsed")

    record = {
        "job_id": job["id"],
        "reason": body["reason"],
        "covered_by_warranty": True,
        "status": "OPEN",
    }
    db.stamp_new(record)
    db.callbacks[record["id"]] = record

    # Covered callback reopens the job into WARRANTY.
    job["status"] = "WARRANTY"
    db.touch(job)

    return response.object_response(serialize(record), 201)


@bp.get("/v1/callbacks/<callback_id>")
def get_callback(callback_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Customer"})
    record = db.callbacks.get(callback_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Callback not found")
    return response.object_response(serialize(record), 200)


@bp.get("/v1/callbacks")
def list_callbacks():
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Customer"})
    limit, offset = parse_pagination()
    job_id = request.args.get("job_id")
    status = request.args.get("status")

    items = list(db.callbacks.values())
    if job_id is not None:
        items = [c for c in items if c["job_id"] == job_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return response.array_response(serialize_list(page), limit, offset, total, 200)


@bp.post("/v1/callbacks/<callback_id>/resolve")
def resolve_callback(callback_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    callback = db.callbacks.get(callback_id)
    if callback is None:
        raise err("ERR_NOT_FOUND", "Callback not found")

    # State: callback OPEN and parent job back in COMPLETED or INVOICED.
    if callback["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Callback must be OPEN to resolve")
    job = db.service_jobs.get(callback["job_id"])
    if job is None or job["status"] not in ("COMPLETED", "INVOICED"):
        raise err("ERR_INVALID_STATE", "Parent job must be COMPLETED or INVOICED to resolve the callback")

    callback["status"] = "RESOLVED"
    db.touch(callback)
    return response.object_response(serialize(callback), 200)
