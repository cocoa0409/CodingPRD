"""InstallSlot endpoints: create (heavily validated), fetch, start, complete, cancel."""
from datetime import timedelta

from flask import Blueprint

import clock
from db import db, stamp_create, touch
from errors import err
from middleware import require_roles
from response import created, ok
from services import calc, serialize
from services.helpers import body, require_fields

bp = Blueprint("install_slots", __name__)


def _accepted_measured_estimate(job_id):
    """Return the job's accepted MEASURED estimate, if any."""
    for e in db.estimates.values():
        if e["job_id"] == job_id and e["status"] == "ACCEPTED" and e["variant"] == "MEASURED":
            return e
    return None


def _intervals_closed_overlap(a_start, a_end, b_start, b_end):
    """Closed-interval intersection: [a_start,a_end] ∩ [b_start,b_end] non-empty."""
    return a_start <= b_end and b_start <= a_end


def _intervals_halfopen_overlap(a_start, a_end, b_start, b_end):
    """Half-open intersection: [a_start,a_end) ∩ [b_start,b_end) non-empty."""
    return a_start < b_end and b_start < a_end


@bp.post("/flooring/install-slots")
@require_roles("Scheduler", "Admin")
def create_slot():
    data = body()
    require_fields(data, ["job_id", "crew_id", "start_at", "end_at"])
    job_id = data["job_id"]
    crew_id = data["crew_id"]
    start_at_raw = data["start_at"]
    end_at_raw = data["end_at"]

    with db.lock:
        # Existence (path has no id here; body FKs left-to-right: job, crew).
        job = db.jobs.get(job_id)
        if job is None:
            raise err("ERR_NOT_FOUND", "Job not found.")
        crew = db.install_crews.get(crew_id)
        if crew is None:
            raise err("ERR_NOT_FOUND", "Crew not found.")

        # 1) Job ACCEPTED + has accepted MEASURED estimate (scheduled_sqft source).
        accepted_est = _accepted_measured_estimate(job_id)
        if job["status"] != "ACCEPTED" or accepted_est is None:
            raise err("ERR_JOB_NOT_ACCEPTED", "Job is not ACCEPTED with an accepted MEASURED estimate.")
        scheduled_sqft = accepted_est["billable_sqft"]

        product = db.products[job["product_id"]]

        # 2) Crew skill must include the job's product category.
        if product["category"] not in crew["skill_categories"]:
            raise err("ERR_CREW_SKILL_MISMATCH", "Crew cannot install this product category.")

        # 3) Interval well-formedness: start_at strictly before end_at, both present/valid.
        try:
            start_at = clock.parse(start_at_raw)
            end_at = clock.parse(end_at_raw)
        except ValueError:
            raise err("ERR_INVALID_INTERVAL", "start_at and end_at must be valid ISO 8601 instants.")
        if not (start_at < end_at):
            raise err("ERR_INVALID_INTERVAL", "start_at must be strictly before end_at.")

        # 4) Job self-overlap: closed-interval intersection with another SCHEDULED slot of this job.
        for s in db.install_slots.values():
            if s["job_id"] == job_id and s["status"] == "SCHEDULED":
                s_start = clock.parse(s["start_at"])
                s_end = clock.parse(s["end_at"])
                if _intervals_closed_overlap(start_at, end_at, s_start, s_end):
                    raise err("ERR_JOB_SLOT_OVERLAP", "Job already has an overlapping scheduled slot.")

        # 5) Crew buffered conflict: candidate [start,end) vs each existing SCHEDULED
        #    slot of the crew expanded by buffer_minutes on each side (half-open).
        buffer = timedelta(minutes=crew["buffer_minutes"])
        for s in db.install_slots.values():
            if s["crew_id"] == crew_id and s["status"] == "SCHEDULED":
                s_start = clock.parse(s["start_at"]) - buffer
                s_end = clock.parse(s["end_at"]) + buffer
                if _intervals_halfopen_overlap(start_at, end_at, s_start, s_end):
                    raise err("ERR_CREW_TIME_CONFLICT", "Crew has a conflicting slot within its buffer.")

        # 6) Daily capacity: day load on candidate's UTC date + scheduled_sqft <= capacity.
        cand_date = start_at.date()
        existing_load = 0.0
        for s in db.install_slots.values():
            if s["crew_id"] == crew_id and s["status"] == "SCHEDULED":
                if clock.parse(s["start_at"]).date() == cand_date:
                    existing_load += s["scheduled_sqft"]
        if existing_load + scheduled_sqft > crew["daily_sqft_capacity"]:
            raise err("ERR_CREW_CAPACITY_EXCEEDED", "Crew daily capacity would be exceeded.")

        record = stamp_create(
            {
                "job_id": job_id,
                "crew_id": crew_id,
                "start_at": start_at_raw,
                "end_at": end_at_raw,
                "scheduled_sqft": scheduled_sqft,
                "status": "SCHEDULED",
            }
        )
        db.install_slots[record["id"]] = record
    return created(serialize.slot_view(record))


@bp.get("/flooring/install-slots/<sid>")
@require_roles("Admin", "Scheduler", "SalesRep")
def get_slot(sid):
    with db.lock:
        s = db.install_slots.get(sid)
        if s is None:
            raise err("ERR_NOT_FOUND", "Install slot not found.")
        return ok(serialize.slot_view(s))


@bp.post("/flooring/install-slots/<sid>/start")
@require_roles("Scheduler", "Admin")
def start_slot(sid):
    with db.lock:
        s = db.install_slots.get(sid)
        if s is None:
            raise err("ERR_NOT_FOUND", "Install slot not found.")
        job = db.jobs.get(s["job_id"])
        if job is None:
            raise err("ERR_NOT_FOUND", "Job not found.")

        # State legality: job ACCEPTED + slot SCHEDULED.
        if job["status"] != "ACCEPTED" or s["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Install can only start from an ACCEPTED job and SCHEDULED slot.")

        # Cross-entity gate: job's MaterialOrder must be RECEIVED.
        received = any(
            m["job_id"] == job["id"] and m["status"] == "RECEIVED"
            for m in db.material_orders.values()
        )
        if not received:
            raise err("ERR_MATERIAL_NOT_RECEIVED", "Material order is not yet RECEIVED.")

        job["status"] = "IN_INSTALL"
        touch(job)
        return ok(serialize.slot_view(s))


@bp.post("/flooring/install-slots/<sid>/complete")
@require_roles("Scheduler", "Admin")
def complete_slot(sid):
    with db.lock:
        s = db.install_slots.get(sid)
        if s is None:
            raise err("ERR_NOT_FOUND", "Install slot not found.")
        job = db.jobs.get(s["job_id"])
        if job is None:
            raise err("ERR_NOT_FOUND", "Job not found.")

        if s["status"] != "SCHEDULED" or job["status"] != "IN_INSTALL":
            raise err("ERR_INVALID_STATE", "Slot must be SCHEDULED and job IN_INSTALL to complete.")

        s["status"] = "DONE"
        touch(s)

        # Bubble-up: job IN_INSTALL -> COMPLETED; compute warranty_risk_score.
        product = db.products[job["product_id"]]
        order = next(
            (m for m in db.material_orders.values() if m["job_id"] == job["id"]), None
        )
        backorder_count = order["backorder_count"] if order is not None else 0
        job["status"] = "COMPLETED"
        # Completion instant anchors the warranty window.
        job["_completed_at"] = clock.iso(clock.now())
        job["warranty_risk_score"] = calc.warranty_risk_score(
            product["category"],
            job["tear_out_sqft"] if job["tear_out_sqft"] is not None else 0,
            backorder_count,
            job["_ever_remeasured"],
        )
        touch(job)
        return ok(serialize.slot_view(s))


@bp.post("/flooring/install-slots/<sid>/cancel")
@require_roles("Scheduler", "Admin")
def cancel_slot(sid):
    with db.lock:
        s = db.install_slots.get(sid)
        if s is None:
            raise err("ERR_NOT_FOUND", "Install slot not found.")
        if s["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Only a SCHEDULED slot can be cancelled.")
        s["status"] = "CANCELLED"
        touch(s)
        return ok(serialize.slot_view(s))
