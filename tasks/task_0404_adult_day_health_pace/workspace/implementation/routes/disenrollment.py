"""Disenrollment request lifecycle + finalize cascade. PRD §3.8."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_roles
from response import success, list_response
from services import common as c
from services import calculations as calc
from services.participant_helpers import recompute_enrolled_count

bp = Blueprint("disenrollment", __name__)

KINDS = {"VOLUNTARY", "INVOLUNTARY"}
REASONS = {"MOVED", "DISSATISFIED", "DECEASED", "LOSS_OF_ELIGIBILITY",
           "NONPAYMENT", "DISRUPTIVE", "FRAUD"}


def req_view(r):
    return dict(r)


@bp.post("/pace/disenrollment-requests")
@require_roles("IntakeCoordinator", "MedicalDirector", "ProgramAdmin")
def create_request():
    body = c.get_body()
    participant_id = c.as_str(body, "participant_id")
    kind = c.as_enum(body, "kind", KINDS)
    reason_code = c.as_enum(body, "reason_code", REASONS)
    requested_effective_date = c.parse_datetime(body, "requested_effective_date")
    c.find_or_404(db.participants, participant_id)

    r = c.base_fields()
    r.update({
        "participant_id": participant_id,
        "kind": kind,
        "reason_code": reason_code,
        "requested_effective_date": c.iso_out(requested_effective_date),
        "lock_in_penalty_cents": 0,
        "status": "SUBMITTED",
    })
    db.disenrollment_requests[r["id"]] = r
    return success(req_view(r), status=201)


@bp.get("/pace/disenrollment-requests/<request_id>")
@require_roles("ProgramAdmin", "IntakeCoordinator", "MedicalDirector", "BillingSpecialist")
def get_request(request_id):
    r = c.find_or_404(db.disenrollment_requests, request_id)
    return success(req_view(r))


@bp.get("/pace/disenrollment-requests")
@require_roles("ProgramAdmin", "IntakeCoordinator", "MedicalDirector", "BillingSpecialist")
def list_requests():
    limit, offset = c.get_pagination()
    items = list(db.disenrollment_requests.values())
    for key in ("participant_id", "kind", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    page, total = c.paginate(items, limit, offset)
    return list_response([req_view(r) for r in page], limit, offset, total)


@bp.post("/pace/disenrollment-requests/<request_id>/approve")
@require_roles("MedicalDirector")
def approve(request_id):
    r = c.find_or_404(db.disenrollment_requests, request_id)
    participant = db.participants.get(r["participant_id"])
    # State (priority 5)
    if r["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Request not SUBMITTED")
    # Participant ENROLLED (priority 7)
    if not participant or participant["status"] != "ENROLLED":
        raise err("ERR_PARTICIPANT_NOT_ENROLLED", "Participant not enrolled")

    r["status"] = "APPROVED"
    c.touch(r)
    participant["status"] = "DISENROLLMENT_PENDING"
    c.touch(participant)
    # enrolled_count is the derived count of ENROLLED participants (PRD §2.6):
    # the participant just left ENROLLED, so the program's count must drop.
    program = db.programs.get(participant["program_id"])
    if program:
        recompute_enrolled_count(program)
        c.touch(program)
    return success(req_view(r))


@bp.post("/pace/disenrollment-requests/<request_id>/deny")
@require_roles("MedicalDirector")
def deny(request_id):
    r = c.find_or_404(db.disenrollment_requests, request_id)
    # State (priority 5)
    if r["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Request not SUBMITTED")
    # Only VOLUNTARY may be denied (priority 16)
    if r["kind"] != "VOLUNTARY":
        raise err("ERR_INVOLUNTARY_CANNOT_DENY", "Involuntary request cannot be denied")
    r["status"] = "DENIED"
    c.touch(r)
    return success(req_view(r))


@bp.post("/pace/disenrollment-requests/<request_id>/withdraw")
@require_roles("IntakeCoordinator")
def withdraw(request_id):
    r = c.find_or_404(db.disenrollment_requests, request_id)
    # State (priority 5)
    if r["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Request not APPROVED")
    # Only VOLUNTARY may be withdrawn (priority 15)
    if r["kind"] != "VOLUNTARY":
        raise err("ERR_WITHDRAW_NOT_ALLOWED", "Involuntary request cannot be withdrawn")
    r["status"] = "WITHDRAWN"
    c.touch(r)
    participant = db.participants.get(r["participant_id"])
    if participant:
        participant["status"] = "ENROLLED"
        c.touch(participant)
        # Participant returns to ENROLLED: derived enrolled_count rises again (PRD §2.6).
        program = db.programs.get(participant["program_id"])
        if program:
            recompute_enrolled_count(program)
            c.touch(program)
    return success(req_view(r))


def _discontinue_plan_orders(care_plan_id):
    for order in db.medication_orders.values():
        if order["care_plan_id"] == care_plan_id and order["status"] in (
                "ORDERED", "ACTIVE", "HELD"):
            order["status"] = "DISCONTINUED"
            c.touch(order)


def _cancel_planned_legs(day_id):
    for leg in db.transport_legs.values():
        if leg["attendance_day_id"] == day_id and leg["status"] == "PLANNED":
            leg["status"] = "CANCELLED"
            c.touch(leg)


@bp.post("/pace/disenrollment-requests/<request_id>/finalize")
@require_roles("BillingSpecialist")
def finalize(request_id):
    r = c.find_or_404(db.disenrollment_requests, request_id)
    body = c.get_body()
    expected_version = c.as_int(body, "expected_participant_version")
    participant = db.participants.get(r["participant_id"])

    # State (priority 5)
    if r["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Request not APPROVED")
    # Participant DISENROLLMENT_PENDING (priority 7)
    if not participant or participant["status"] != "DISENROLLMENT_PENDING":
        raise err("ERR_PARTICIPANT_NOT_ENROLLED", "Participant not in DISENROLLMENT_PENDING")
    # OCC (priority 26)
    if expected_version != participant["version"]:
        raise err("ERR_STALE_VERSION", "Participant version mismatch")

    program = db.programs.get(participant["program_id"])
    requested_dt = c.parse_iso(r["requested_effective_date"])

    # --- Cascade (atomic) ---
    # Enrollment → CLOSED; disenrollment_effective_date := requested_effective_date
    enrollment = db.enrollments.get(participant.get("active_enrollment_id"))
    if enrollment:
        enrollment["status"] = "CLOSED"
        enrollment["disenrollment_effective_date"] = c.iso_out(requested_dt)
        c.touch(enrollment)

    # Lock-in penalty (VOLUNTARY + before lock_in_end_date)
    penalty = 0
    if enrollment:
        lock_in_end = c.parse_iso(enrollment["lock_in_end_date"])
        penalty = calc.lock_in_penalty(
            r["kind"], requested_dt, lock_in_end,
            program["medicare_monthly_rate_cents"], program["lock_in_days"],
        )
    r["lock_in_penalty_cents"] = penalty

    # ACTIVE care plan teardown: SUPERSEDED (non-death) or VOID (DECEASED)
    active_plan_id = participant.get("active_care_plan_id")
    if active_plan_id:
        plan = db.care_plans.get(active_plan_id)
        if plan and plan["status"] == "ACTIVE":
            plan["status"] = "VOID" if r["reason_code"] == "DECEASED" else "SUPERSEDED"
            c.touch(plan)
            _discontinue_plan_orders(plan["id"])

    # Every SCHEDULED/CHECKED_IN AttendanceDay → CANCELLED; legs cascaded
    for day in db.attendance_days.values():
        if day["participant_id"] != participant["id"]:
            continue
        if day["status"] in ("SCHEDULED", "CHECKED_IN"):
            day["status"] = "CANCELLED"
            c.touch(day)
            _cancel_planned_legs(day["id"])

    # Clear participant FKs; program enrolled_count -= 1
    participant["active_enrollment_id"] = None
    participant["active_care_plan_id"] = None
    participant["status"] = "DISENROLLED"
    c.touch(participant)
    # enrolled_count is the derived count of ENROLLED participants (PRD §2.6);
    # recompute so it never drifts (the participant was already PENDING here).
    if program:
        recompute_enrolled_count(program)
        c.touch(program)

    r["status"] = "FINALIZED"
    c.touch(r)
    return success(req_view(r))
