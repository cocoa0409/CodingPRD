"""Estimate endpoints (PRD §3.3, §3.4).

Create runs estimate_quoted_total and OCC on the parent job's version; send,
accept (with sibling supersede + job bubble to QUOTED), reject.
"""
from decimal import Decimal

from flask import Blueprint, request

import db
import response
from errors import err
from helpers import (get_json_body, paginate, parse_pagination, require_enum,
                     require_fields, require_int, require_number,
                     round_half_up, serialize, serialize_list, sort_by_created)
from middleware import get_identity, require_roles
from services import domain

bp = Blueprint("estimates", __name__)

PRICING_MODES = {"FLAT_RATE", "TIME_MATERIALS"}


def _hourly_rate_for_job(job):
    """The dispatched technician's hourly_rate_cents if a technician is known at
    quote time, else the default zone rate (PRD §3.3)."""
    cands = [
        d for d in db.dispatches.values()
        if d["job_id"] == job["id"] and d["status"] != "CANCELLED"
    ]
    if cands:
        cands.sort(key=lambda d: (d["created_at"], d["_seq"]))
        tech = db.technicians.get(cands[-1]["technician_id"])
        if tech is not None:
            return tech["hourly_rate_cents"]
    return domain.DEFAULT_HOURLY_RATE_CENTS


def _quoted_total(pricing_mode, flat_rate_cents, estimated_labor_hours,
                  estimated_material_cents, hourly_rate_cents):
    if pricing_mode == "FLAT_RATE":
        return flat_rate_cents
    # TIME_MATERIALS
    labor_cents = round_half_up(Decimal(str(estimated_labor_hours)) * Decimal(str(hourly_rate_cents)))
    return labor_cents + estimated_material_cents


@bp.post("/v1/estimates")
def create_estimate():
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    body = get_json_body()

    # Existence: job_id (body FK).
    require_fields(body, ["job_id"])
    job = db.service_jobs.get(body["job_id"])
    if job is None:
        raise err("ERR_NOT_FOUND", "Service job not found")

    # Body well-formedness (priority 5) before OCC (priority 6).
    require_fields(body, ["pricing_mode", "expected_job_version"])
    require_enum(body["pricing_mode"], PRICING_MODES, "pricing_mode")
    require_int(body["expected_job_version"], "expected_job_version")

    pricing_mode = body["pricing_mode"]
    flat_rate_cents = body.get("flat_rate_cents", 0) or 0
    estimated_labor_hours = body.get("estimated_labor_hours", 0) or 0
    estimated_material_cents = body.get("estimated_material_cents", 0) or 0

    if pricing_mode == "FLAT_RATE":
        if body.get("flat_rate_cents") is None:
            raise err("ERR_INVALID_REQUEST", "flat_rate_cents is required for FLAT_RATE")
        require_int(flat_rate_cents, "flat_rate_cents")
        if flat_rate_cents < 0:
            raise err("ERR_INVALID_REQUEST", "flat_rate_cents must be >= 0")
    else:  # TIME_MATERIALS
        if body.get("estimated_labor_hours") is None:
            raise err("ERR_INVALID_REQUEST", "estimated_labor_hours is required for TIME_MATERIALS")
        require_number(estimated_labor_hours, "estimated_labor_hours")
        if estimated_labor_hours < 0:
            raise err("ERR_INVALID_REQUEST", "estimated_labor_hours must be >= 0")
        require_int(estimated_material_cents, "estimated_material_cents")
        if estimated_material_cents < 0:
            raise err("ERR_INVALID_REQUEST", "estimated_material_cents must be >= 0")

    # OCC: expected_job_version must equal current job version.
    if body["expected_job_version"] != job["version"]:
        raise err("ERR_STALE_VERSION", "expected_job_version does not match the job's current version")

    hourly_rate = _hourly_rate_for_job(job)
    quoted_total = _quoted_total(
        pricing_mode, flat_rate_cents, estimated_labor_hours,
        estimated_material_cents, hourly_rate,
    )

    record = {
        "job_id": job["id"],
        "pricing_mode": pricing_mode,
        "flat_rate_cents": flat_rate_cents,
        "estimated_labor_hours": estimated_labor_hours,
        "estimated_material_cents": estimated_material_cents,
        "quoted_total_cents": quoted_total,
        "status": "DRAFT",
    }
    db.stamp_new(record)
    db.estimates[record["id"]] = record

    # Successfully creating an estimate increments the parent job version by 1.
    db.touch(job)
    return response.object_response(serialize(record), 201)


@bp.get("/v1/estimates/<estimate_id>")
def get_estimate(estimate_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Customer"})
    record = db.estimates.get(estimate_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Estimate not found")
    return response.object_response(serialize(record), 200)


@bp.get("/v1/estimates")
def list_estimates():
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Customer"})
    limit, offset = parse_pagination()
    job_id = request.args.get("job_id")
    status = request.args.get("status")

    items = list(db.estimates.values())
    if job_id is not None:
        items = [e for e in items if e["job_id"] == job_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return response.array_response(serialize_list(page), limit, offset, total, 200)


@bp.post("/v1/estimates/<estimate_id>/send")
def send_estimate(estimate_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    estimate = db.estimates.get(estimate_id)
    if estimate is None:
        raise err("ERR_NOT_FOUND", "Estimate not found")
    job = db.service_jobs.get(estimate["job_id"])

    # State: estimate DRAFT and parent job DRAFT or QUOTED.
    if estimate["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Estimate must be DRAFT to send")
    if job is None or job["status"] not in ("DRAFT", "QUOTED"):
        raise err("ERR_INVALID_STATE", "Parent job must be DRAFT or QUOTED to send an estimate")

    estimate["status"] = "SENT"
    db.touch(estimate)
    return response.object_response(serialize(estimate), 200)


@bp.post("/v1/estimates/<estimate_id>/accept")
def accept_estimate(estimate_id):
    user_id, role = get_identity()
    require_roles(role, {"Customer"})
    estimate = db.estimates.get(estimate_id)
    if estimate is None:
        raise err("ERR_NOT_FOUND", "Estimate not found")
    job = db.service_jobs.get(estimate["job_id"])

    # Ownership: accepting customer must own the parent job.
    if job is None or job["customer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Customer does not own the parent job")

    # State: estimate must be SENT.
    if estimate["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Estimate must be SENT to accept")

    estimate["status"] = "ACCEPTED"
    db.touch(estimate)

    # Supersede all sibling SENT/DRAFT estimates on the same job.
    for e in db.estimates.values():
        if (e["job_id"] == job["id"] and e["id"] != estimate["id"]
                and e["status"] in ("SENT", "DRAFT")):
            e["status"] = "SUPERSEDED"
            db.touch(e)

    # Parent job: pricing_mode := this mode; DRAFT/QUOTED -> QUOTED.
    job["pricing_mode"] = estimate["pricing_mode"]
    if job["status"] in ("DRAFT", "QUOTED"):
        job["status"] = "QUOTED"
    db.touch(job)

    return response.object_response(serialize(estimate), 200)


@bp.post("/v1/estimates/<estimate_id>/reject")
def reject_estimate(estimate_id):
    user_id, role = get_identity()
    require_roles(role, {"Customer"})
    estimate = db.estimates.get(estimate_id)
    if estimate is None:
        raise err("ERR_NOT_FOUND", "Estimate not found")
    job = db.service_jobs.get(estimate["job_id"])

    # Ownership: rejecting customer must own the parent job.
    if job is None or job["customer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Customer does not own the parent job")

    # State: estimate must be SENT.
    if estimate["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Estimate must be SENT to reject")

    estimate["status"] = "REJECTED"
    db.touch(estimate)
    return response.object_response(serialize(estimate), 200)
