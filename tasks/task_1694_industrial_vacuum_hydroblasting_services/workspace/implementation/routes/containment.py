"""Containment records (PRD 3.4)."""

from flask import Blueprint, request

from db import store
from errors import invalid_state, not_found
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.calculations import MIN_CAPTURE_RATIO
from util import dec, get_body, list_paginated, new_entity, req_field, rhu, touch

bp = Blueprint("containment", __name__)


def _get_record(record_id):
    record = store.containment_records.get(record_id)
    if record is None:
        raise not_found("Containment record not found")
    return record


@bp.post("/v1/containment-records")
def create_containment_record():
    require_roles(["FieldSupervisor"])
    body = get_body()
    job_id = req_field(body, "job_id")
    water_used = req_field(body, "water_used_gallons", kind="int", gt_zero=True)
    water_captured = req_field(body, "water_captured_gallons", kind="int",
                               gte_zero=True)
    job = store.jobs.get(job_id)
    if job is None:
        raise not_found("Job not found")
    if job["execution_status"] != "IN_PROGRESS":
        raise invalid_state(
            "Containment can only be logged while the job is IN_PROGRESS")
    existing = [c for c in store.containment_records.values()
                if c["job_id"] == job_id]
    sequence = max((c["sequence"] for c in existing), default=0) + 1
    capture_ratio = rhu(dec(water_captured) / dec(water_used), 4)
    record = new_entity(store.containment_records, {
        "job_id": job_id,
        "sequence": sequence,
        "water_used_gallons": water_used,
        "water_captured_gallons": water_captured,
        "capture_ratio": capture_ratio,
        "status": "LOGGED",
    })
    return success_object(record, status=201)


@bp.get("/v1/containment-records")
def list_containment_records():
    require_roles(ALL_ROLES)
    filters = {}
    if request.args.get("job_id") is not None:
        filters["job_id"] = request.args["job_id"]
    page, limit, offset, total = list_paginated(store.containment_records,
                                                filters, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/v1/containment-records/<recordId>")
def get_containment_record(recordId):
    require_roles(ALL_ROLES)
    return success_object(_get_record(recordId))


@bp.post("/v1/containment-records/<recordId>/verify")
def verify_containment_record(recordId):
    require_roles(["ProjectManager"])
    record = _get_record(recordId)
    if record["status"] != "LOGGED":
        raise invalid_state("Only a LOGGED containment record can be verified")
    # Same verify call branches on the computed ratio; 0.9500 exactly passes.
    record["status"] = ("VERIFIED" if dec(record["capture_ratio"]) >= MIN_CAPTURE_RATIO
                        else "DEFICIENT")
    touch(record)
    return success_object(record)
