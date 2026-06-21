"""Dispatch endpoints (PRD §3.4, §3.5).

Create routes a technician (OCC on job version; license/on-call/zone/overlap
gating; bubbles QUOTED -> SCHEDULED); depart/arrive drive the field lifecycle;
reschedule re-runs the overlap check; cancel frees the technician window.

Business-check precedence on create (PRD §2.6): state (ERR_INVALID_STATE) then
license, on-call, zone, double-booking — in that order.
"""
from flask import Blueprint, request

import clock
import db
import response
from errors import err
from helpers import (get_json_body, paginate, parse_pagination,
                     parse_datetime_field, require_fields, require_int,
                     serialize, serialize_list, sort_by_created)
from middleware import get_identity, require_roles
from services import domain

bp = Blueprint("dispatches", __name__)

ACTIVE_DISPATCH_STATES = ("ASSIGNED", "EN_ROUTE", "ON_SITE")


def _overlaps(technician_id, start, end, exclude_id=None):
    """True when [start, end) overlaps an active dispatch on the same technician
    (half-open intervals, microsecond resolution, PRD §3.4)."""
    for d in db.dispatches.values():
        if d["technician_id"] != technician_id:
            continue
        if exclude_id is not None and d["id"] == exclude_id:
            continue
        if d["status"] not in ACTIVE_DISPATCH_STATES:
            continue
        ex_start = clock.parse_iso(d["window_start"])
        ex_end = clock.parse_iso(d["window_end"])
        # Conflict iff new.start < existing.end AND existing.start < new.end.
        if start < ex_end and ex_start < end:
            return True
    return False


@bp.post("/v1/dispatches")
def create_dispatch():
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    body = get_json_body()

    # Existence: job_id then technician_id (body FKs, left-to-right).
    require_fields(body, ["job_id"])
    job = db.service_jobs.get(body["job_id"])
    if job is None:
        raise err("ERR_NOT_FOUND", "Service job not found")
    require_fields(body, ["technician_id"])
    technician = db.technicians.get(body["technician_id"])
    if technician is None:
        raise err("ERR_NOT_FOUND", "Technician not found")

    # Body well-formedness (priority 5).
    require_fields(body, ["window_start", "window_end", "expected_job_version"])
    require_int(body["expected_job_version"], "expected_job_version")
    window_start = parse_datetime_field(body["window_start"], "window_start")
    window_end = parse_datetime_field(body["window_end"], "window_end")
    if not (window_start < window_end):
        raise err("ERR_INVALID_REQUEST", "window_start must be strictly before window_end")

    # OCC (priority 6).
    if body["expected_job_version"] != job["version"]:
        raise err("ERR_STALE_VERSION", "expected_job_version does not match the job's current version")

    # State (priority 7): a dispatch is created against a QUOTED job (initial
    # routing) or a WARRANTY job (re-dispatch for warranty work, PRD §3.8). A
    # QUOTED job bubbles to SCHEDULED on this create; a WARRANTY job remains
    # WARRANTY until the dispatch arrives on site (arrive: WARRANTY ->
    # IN_PROGRESS), which is the only path that reaches the WARRANTY -> work
    # loop the PRD describes.
    if job["status"] not in ("QUOTED", "WARRANTY"):
        raise err("ERR_INVALID_STATE", "Job must be QUOTED (or WARRANTY for re-dispatch) to dispatch")

    # License gating (priority 8): PANEL/EV_CHARGER require MASTER.
    if job["scope"] in domain.PERMIT_SCOPES and technician["license_class"] != "MASTER":
        raise err("ERR_LICENSE_INSUFFICIENT", "PANEL/EV_CHARGER work requires a MASTER technician")

    # On-call gating (priority 9): EMERGENCY requires on_call technician.
    if job["priority"] == "EMERGENCY" and not technician["on_call"]:
        raise err("ERR_TECH_NOT_ON_CALL", "EMERGENCY dispatch requires an on-call technician")

    # Zone match (priority 10).
    customer = db.customers.get(job["customer_id"])
    if technician["service_zone"] != domain.job_zone(customer):
        raise err("ERR_ZONE_MISMATCH", "Technician zone does not match the job zone")

    # Double-booking (priority 11).
    if _overlaps(technician["id"], window_start, window_end):
        raise err("ERR_TECH_DOUBLE_BOOKED", "Technician already has an overlapping dispatch")

    record = {
        "job_id": job["id"],
        "technician_id": technician["id"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "eta": body["window_start"],
        "status": "ASSIGNED",
    }
    db.stamp_new(record)
    db.dispatches[record["id"]] = record

    # Bubble QUOTED -> SCHEDULED (a WARRANTY job stays WARRANTY until arrive)
    # and increment job version (PRD §2.5, §3.4).
    if job["status"] == "QUOTED":
        job["status"] = "SCHEDULED"
    db.touch(job)
    return response.object_response(serialize(record), 201)


@bp.get("/v1/dispatches/<dispatch_id>")
def get_dispatch(dispatch_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Technician", "Customer"})
    record = db.dispatches.get(dispatch_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Dispatch not found")
    return response.object_response(serialize(record), 200)


@bp.get("/v1/dispatches")
def list_dispatches():
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Technician"})
    limit, offset = parse_pagination()
    job_id = request.args.get("job_id")
    technician_id = request.args.get("technician_id")
    status = request.args.get("status")

    items = list(db.dispatches.values())
    if job_id is not None:
        items = [d for d in items if d["job_id"] == job_id]
    if technician_id is not None:
        items = [d for d in items if d["technician_id"] == technician_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return response.array_response(serialize_list(page), limit, offset, total, 200)


@bp.post("/v1/dispatches/<dispatch_id>/depart")
def depart(dispatch_id):
    user_id, role = get_identity()
    require_roles(role, {"Technician"})
    dispatch = db.dispatches.get(dispatch_id)
    if dispatch is None:
        raise err("ERR_NOT_FOUND", "Dispatch not found")

    # Ownership: acting technician must be the assigned technician.
    if dispatch["technician_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Only the assigned technician may depart")

    # State: ASSIGNED -> EN_ROUTE.
    if dispatch["status"] != "ASSIGNED":
        raise err("ERR_INVALID_STATE", "Dispatch must be ASSIGNED to depart")

    dispatch["status"] = "EN_ROUTE"
    db.touch(dispatch)
    return response.object_response(serialize(dispatch), 200)


@bp.post("/v1/dispatches/<dispatch_id>/arrive")
def arrive(dispatch_id):
    user_id, role = get_identity()
    require_roles(role, {"Technician"})
    dispatch = db.dispatches.get(dispatch_id)
    if dispatch is None:
        raise err("ERR_NOT_FOUND", "Dispatch not found")

    # Ownership: acting technician must be the assigned technician.
    if dispatch["technician_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Only the assigned technician may arrive")

    # State: EN_ROUTE -> ON_SITE.
    if dispatch["status"] != "EN_ROUTE":
        raise err("ERR_INVALID_STATE", "Dispatch must be EN_ROUTE to arrive")

    dispatch["status"] = "ON_SITE"
    db.touch(dispatch)

    # Parent job: SCHEDULED or WARRANTY -> IN_PROGRESS.
    job = db.service_jobs.get(dispatch["job_id"])
    if job is not None and job["status"] in ("SCHEDULED", "WARRANTY"):
        job["status"] = "IN_PROGRESS"
        db.touch(job)

    return response.object_response(serialize(dispatch), 200)


@bp.post("/v1/dispatches/<dispatch_id>/reschedule")
def reschedule(dispatch_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    dispatch = db.dispatches.get(dispatch_id)
    if dispatch is None:
        raise err("ERR_NOT_FOUND", "Dispatch not found")

    body = get_json_body()
    require_fields(body, ["window_start", "window_end"])
    window_start = parse_datetime_field(body["window_start"], "window_start")
    window_end = parse_datetime_field(body["window_end"], "window_end")
    if not (window_start < window_end):
        raise err("ERR_INVALID_REQUEST", "window_start must be strictly before window_end")

    # State: only an ASSIGNED or EN_ROUTE dispatch may be rescheduled.
    if dispatch["status"] not in ("ASSIGNED", "EN_ROUTE"):
        raise err("ERR_INVALID_STATE", "Only an ASSIGNED or EN_ROUTE dispatch may be rescheduled")

    # Re-run overlap check against the technician's other active dispatches.
    if _overlaps(dispatch["technician_id"], window_start, window_end, exclude_id=dispatch["id"]):
        raise err("ERR_TECH_DOUBLE_BOOKED", "New window overlaps an existing active dispatch")

    dispatch["window_start"] = body["window_start"]
    dispatch["window_end"] = body["window_end"]
    dispatch["eta"] = body["window_start"]
    db.touch(dispatch)
    return response.object_response(serialize(dispatch), 200)


@bp.post("/v1/dispatches/<dispatch_id>/cancel")
def cancel(dispatch_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    dispatch = db.dispatches.get(dispatch_id)
    if dispatch is None:
        raise err("ERR_NOT_FOUND", "Dispatch not found")

    # State: ASSIGNED or EN_ROUTE.
    if dispatch["status"] not in ("ASSIGNED", "EN_ROUTE"):
        raise err("ERR_INVALID_STATE", "Only an ASSIGNED or EN_ROUTE dispatch may be cancelled")

    dispatch["status"] = "CANCELLED"
    db.touch(dispatch)
    return response.object_response(serialize(dispatch), 200)
