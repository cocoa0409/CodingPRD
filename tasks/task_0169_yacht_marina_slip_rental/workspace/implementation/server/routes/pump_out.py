"""Pump-out job routes."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import iso_format, parse_iso
from ..common import bump, get_json_body, positive_int, require_fields, stamp_new
from ..errors import ApiError
from ..marina_helpers import (
    enforce_boater_owns,
    get_marina,
    get_pump_out_job,
    get_reservation,
    parse_required_iso,
    schedule_overlaps_pump_out,
)
from ..response import respond
from ..serializers import pump_out_view
from ..store import store


bp = Blueprint("pump_out", __name__, url_prefix="/marinas")


@bp.post("/<marina_id>/pump-out-jobs")
@require_auth("Boater", "DockMaster")
def create_pump_out(marina_id: str):
    body = get_json_body()
    require_fields(body, "reservation_id", "scheduled_start", "scheduled_end")
    start = parse_required_iso(body, "scheduled_start")
    end = parse_required_iso(body, "scheduled_end")
    if not (end > start):
        raise ApiError("ERR_BAD_REQUEST", "scheduled_end must be after scheduled_start")
    with store.lock:
        get_marina(marina_id)
        res = get_reservation(marina_id, body["reservation_id"])
        if g.user_role == "Boater":
            enforce_boater_owns(res["boater_id"])
        if res.get("status") != "CHECKED_IN":
            raise ApiError("ERR_INVALID_STATE", "Reservation must be CHECKED_IN")
        # Overlap with other SCHEDULED pump-outs on the same slip
        if schedule_overlaps_pump_out(res["slip_id"], start, end):
            raise ApiError("ERR_PUMP_OUT_CONFLICT", "Pump-out window overlaps another scheduled job")
        job = {
            "marina_id": marina_id,
            "reservation_id": res["id"],
            "scheduled_start": iso_format(start),
            "scheduled_end": iso_format(end),
            "status": "SCHEDULED",
            "tank_gallons_drained": None,
        }
        stamp_new(job)
        store.pump_out_jobs[job["id"]] = job
    return respond(pump_out_view(job), 201)


@bp.post("/<marina_id>/pump-out-jobs/<job_id>/complete")
@require_auth("DockMaster")
def complete_pump_out(marina_id: str, job_id: str):
    body = get_json_body()
    require_fields(body, "tank_gallons_drained")
    gallons = positive_int(body["tank_gallons_drained"], "tank_gallons_drained")
    with store.lock:
        marina = get_marina(marina_id)
        job = get_pump_out_job(marina_id, job_id)
        if job.get("status") != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "Pump-out job is not SCHEDULED")
        current = parse_iso(marina["current_date"])
        sched_start = parse_iso(job["scheduled_start"])
        if current < sched_start:
            raise ApiError("ERR_INVALID_STATE", "Marina clock has not reached scheduled_start")

        job["status"] = "COMPLETED"
        job["tank_gallons_drained"] = gallons
        bump(job)

        # If parent reservation is liveaboard, append synthetic utility reading
        res = store.reservations.get(job["reservation_id"])
        if res is not None and res.get("liveaboard"):
            reading = {
                "reservation_id": res["id"],
                "read_at": job["scheduled_end"],
                "kwh_delta": 0,
                "water_gallons_delta": gallons,
                "applied_in_settlement": False,
            }
            stamp_new(reading, with_common=False)
            store.utility_readings[reading["id"]] = reading

        return respond(pump_out_view(job), 200)


@bp.post("/<marina_id>/pump-out-jobs/<job_id>/cancel")
@require_auth("Boater", "DockMaster")
def cancel_pump_out(marina_id: str, job_id: str):
    with store.lock:
        get_marina(marina_id)
        job = get_pump_out_job(marina_id, job_id)
        if g.user_role == "Boater":
            res = store.reservations.get(job.get("reservation_id"))
            if res is None:
                raise ApiError("ERR_NOT_FOUND", "Reservation not found")
            enforce_boater_owns(res["boater_id"])
        if job.get("status") != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "Pump-out job is not SCHEDULED")
        job["status"] = "CANCELLED"
        bump(job)
        return respond(pump_out_view(job), 200)
