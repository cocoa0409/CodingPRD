"""Lift slots: booking gates (moratorium, capacity, insurance), temporal
conflict, deposit gate, completion, cancellation (PRD 3.3)."""

from flask import Blueprint, request

import clock
import db
import response
from errors import (
    not_found, invalid_state, already_terminal, validation, ApiError,
    ERR_ENV_MORATORIUM, ERR_LIFT_CAPACITY_EXCEEDED, ERR_INSURANCE_MISSING,
    ERR_LIFT_SLOT_CONFLICT, ERR_JOB_NOT_READY_FOR_SPLASH, ERR_DEPOSIT_SHORTFALL,
    ERR_STAND_ASSIGNMENT_MISSING,
)
from middleware import require_roles
from money import LIFT_CAPACITY_TONS
from services import insurance as insurance_svc, lifecycle, storage as storage_svc
from services.overlap import lift_slot_conflict
from validation import get_body, req_str, req_enum, req_datetime, req_number, parse_pagination, page
from .jobs import get_job_or_404, TERMINAL_JOB_STATES

bp = Blueprint("lift_slots", __name__)

SLOT_KINDS = ("HAUL_OUT", "SPLASH")
TERMINAL_SLOT_STATES = ("COMPLETED", "CANCELLED", "NO_SHOW")


def get_slot_or_404(slot_id):
    slot = db.slots.get(slot_id)
    if slot is None:
        raise not_found(f"LiftSlot '{slot_id}' does not exist")
    return slot


def _in_moratorium(dt):
    """Month-day in [04-01, 05-31] inclusive: any date in April or May."""
    return dt.month in (4, 5)


@bp.post("/yard/lift-slots")
@require_roles("YardManager")
def create_slot():
    body = get_body()
    job_id = req_str(body, "job_id")
    job = get_job_or_404(job_id)
    kind = req_enum(body, "kind", SLOT_KINDS)
    start = req_datetime(body, "scheduled_start")
    end = req_datetime(body, "scheduled_end")
    if not end > start:
        raise validation("scheduled_end must be strictly after scheduled_start")
    displacement = req_number(body, "vessel_displacement_tons", gt=0)

    # Gate 7: state legality.
    if job["status"] in TERMINAL_JOB_STATES:
        raise already_terminal(f"RefitJob is in terminal state {job['status']}")
    if kind == "HAUL_OUT":
        if job["status"] != "INTAKE":
            raise invalid_state("A haul-out slot may be booked only while the job is INTAKE")
    else:  # SPLASH
        if job["status"] != "READY_FOR_SPLASH":
            raise ApiError(ERR_JOB_NOT_READY_FOR_SPLASH, 409,
                           "SPLASH booking requires the job to be READY_FOR_SPLASH")

    # Business safety gates in pinned order (PRD 3.3): moratorium, lift rating,
    # insurance.
    if kind == "HAUL_OUT" and _in_moratorium(start):
        raise ApiError(ERR_ENV_MORATORIUM, 409,
                       "Haul-out is prohibited during the Apr 1 - May 31 moratorium")
    if displacement > LIFT_CAPACITY_TONS:
        raise ApiError(ERR_LIFT_CAPACITY_EXCEEDED, 409,
                       "vessel_displacement_tons exceeds the 60-ton lift rating")
    if insurance_svc.qualifying_certificate_for_slot(job["vessel_id"], start.date()) is None:
        raise ApiError(ERR_INSURANCE_MISSING, 409,
                       "No qualifying insurance certificate for the scheduled start date")

    # Temporal conflict across the single travel lift.
    if lift_slot_conflict(start, end):
        raise ApiError(ERR_LIFT_SLOT_CONFLICT, 409,
                       "Slot window plus 30-minute buffer intersects an existing slot")

    # Fiscal gate for splash bookings.
    if kind == "SPLASH" and not storage_svc.deposit_satisfied(job["id"]):
        raise ApiError(ERR_DEPOSIT_SHORTFALL, 409,
                       "Posted deposits are below the required 25% deposit")

    now = db.now_iso()
    slot = {
        "id": db.new_id(),
        "job_id": job["id"],
        "kind": kind,
        "scheduled_start": body["scheduled_start"],
        "scheduled_end": body["scheduled_end"],
        "vessel_displacement_tons": displacement,
        "status": "BOOKED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "_start": start,
        "_end": end,
    }
    db.slots[slot["id"]] = slot
    if kind == "HAUL_OUT":
        job["status"] = "HAUL_SCHEDULED"
        db.touch(job)
    return response.success_object(db.pub(slot), status=201)


@bp.get("/yard/refit-jobs/<jobId>/lift-slots")
@require_roles("YardManager", "ServiceWriter")
def list_slots(jobId):
    job = get_job_or_404(jobId)
    limit, offset = parse_pagination()
    kind = request.args.get("kind")
    status = request.args.get("status")
    items = [s for s in db.slots.values() if s["job_id"] == job["id"]]
    if kind is not None:
        items = [s for s in items if s["kind"] == kind]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items, total = page(items, limit, offset)
    return response.success_list(items, limit, offset, total)


@bp.post("/yard/lift-slots/<slotId>/complete")
@require_roles("YardManager")
def complete_slot(slotId):
    slot = get_slot_or_404(slotId)
    if slot["status"] in TERMINAL_SLOT_STATES:
        raise already_terminal(f"LiftSlot is in terminal state {slot['status']}")
    now_dt = clock.now()
    if not (slot["_start"] <= now_dt <= slot["_end"]):
        raise invalid_state("Slot may be completed only within its scheduled window")
    job = db.jobs.get(slot["job_id"])

    if slot["kind"] == "HAUL_OUT":
        active_asn = any(
            a["job_id"] == slot["job_id"] and a["status"] == "ACTIVE"
            for a in db.assignments.values()
        )
        if not active_asn:
            raise ApiError(ERR_STAND_ASSIGNMENT_MISSING, 409,
                           "HAUL_OUT completion requires an ACTIVE stand assignment")
        slot["status"] = "COMPLETED"
        db.touch(slot)
        if job is not None and job["status"] == "HAUL_SCHEDULED":
            today = clock.today()
            job["status"] = "ON_HARD"
            job["hauled_at"] = today.isoformat()
            job["_hauled"] = today
            job["lay_days"] = 0
            job["last_accrual_date"] = None
            job["_last_accrual"] = None
            db.touch(job)
    else:  # SPLASH
        slot["status"] = "COMPLETED"
        db.touch(slot)
        if job is not None and job["status"] == "READY_FOR_SPLASH":
            today = clock.today()
            job["status"] = "AWAITING_TRIAL"
            job["splashed_at"] = today.isoformat()
            db.touch(job)
            for a in db.assignments.values():
                if a["job_id"] == job["id"] and a["status"] == "ACTIVE":
                    lifecycle.release_assignment(a)
    return response.success_object(db.pub(slot))


@bp.post("/yard/lift-slots/<slotId>/cancel")
@require_roles("YardManager")
def cancel_slot(slotId):
    slot = get_slot_or_404(slotId)
    if slot["status"] in TERMINAL_SLOT_STATES:
        raise already_terminal(f"LiftSlot is in terminal state {slot['status']}")
    # HAUL_OUT cancellation reverts the job HAUL_SCHEDULED -> INTAKE.
    lifecycle.cancel_slot(slot, revert_haul_job=True)
    return response.success_object(db.pub(slot))
