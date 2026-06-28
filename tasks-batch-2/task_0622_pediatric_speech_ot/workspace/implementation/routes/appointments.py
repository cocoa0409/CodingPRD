"""Appointment endpoints (PRD §3.5, §3.6)."""

from flask import Blueprint, request

import errors
from errors import ApiError
from db import db
from response import success, list_success
from middleware import require_roles, ALL_ROLES
from validation import get_body, require_str, require_int, require_iso_datetime, bad
from services.common import new_record, touch, lookup, paginate, sorted_by_created
from services import serialize, engine, booking
from clock import parse_iso

bp = Blueprint("appointments", __name__)


@bp.route("/clinic/appointments", methods=["POST"])
@require_roles("ClinicAdmin", "SchedulingCoordinator")
def book(user_id=None, role=None):
    body = get_body()
    child_id = require_str(body, "child_id")
    therapist_id = require_str(body, "therapist_id")
    authorization_id = require_str(body, "authorization_id")
    plan_of_care_id = require_str(body, "plan_of_care_id")
    start_dt = require_iso_datetime(body, "start_time")
    end_dt = require_iso_datetime(body, "end_time")
    # end_time must be after start_time.
    if end_dt <= start_dt:
        raise bad("end_time must be after start_time.")
    # FK existence (PRD §2.5) — left-to-right is irrelevant for body FKs; all
    # must exist or ERR_NOT_FOUND.
    lookup(db.children, child_id)
    lookup(db.therapists, therapist_id)
    lookup(db.authorizations, authorization_id)
    lookup(db.plans_of_care, plan_of_care_id)
    appt = booking.book_appointment(
        child_id, therapist_id, authorization_id, plan_of_care_id,
        start_dt, end_dt, from_waitlist_entry_id=None,
    )
    return success(serialize.appointment(appt), status=201)


@bp.route("/clinic/appointments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_appointments(user_id=None, role=None):
    items = list(db.appointments.values())
    for field in ("child_id", "therapist_id", "authorization_id",
                  "plan_of_care_id", "from_waitlist_entry_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [a for a in items if a[field] == val]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return list_success([serialize.appointment(a) for a in page], limit, offset, total)


@bp.route("/clinic/appointments/<appointment_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_appointment(appointment_id, user_id=None, role=None):
    rec = lookup(db.appointments, appointment_id)
    return success(serialize.appointment(rec), status=200)


@bp.route("/clinic/appointments/<appointment_id>/complete", methods=["POST"])
@require_roles("Therapist")
def complete(appointment_id, user_id=None, role=None):
    appt = lookup(db.appointments, appointment_id)
    if appt["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_APPOINTMENT_NOT_SCHEDULED, 409,
                       "Appointment must be SCHEDULED to complete.")
    # Cannot complete a future appointment.
    if db.clock.now() < parse_iso(appt["start_time"]):
        raise ApiError(errors.ERR_APPOINTMENT_IN_FUTURE, 409,
                       "Cannot complete a future appointment.")
    body = get_body()
    narrative = require_str(body, "narrative", min_len=10)
    minutes_delivered = require_int(body, "minutes_delivered", minimum=1)
    entries = body.get("goal_progress_entries", [])
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise bad("goal_progress_entries must be an array.")
    parsed_entries = []
    for item in entries:
        if not isinstance(item, dict):
            raise bad("Each goal_progress_entry must be an object.")
        if "goal_id" not in item or not isinstance(item["goal_id"], str):
            raise bad("Each goal_progress_entry requires a string goal_id.")
        recorded = item.get("recorded_pct")
        if isinstance(recorded, bool) or not isinstance(recorded, int):
            raise bad("recorded_pct must be an integer.")
        if recorded < 0 or recorded > 100:
            raise bad("recorded_pct must be between 0 and 100.")
        parsed_entries.append({"goal_id": item["goal_id"], "recorded_pct": recorded})

    # Every goal_id must belong to the appointment's plan_of_care.
    plan_id = appt["plan_of_care_id"]
    for pe in parsed_entries:
        goal = db.goals.get(pe["goal_id"])
        if goal is None or goal["plan_of_care_id"] != plan_id:
            raise ApiError(errors.ERR_GOAL_PLAN_MISMATCH, 409,
                           "A goal_progress_entries goal_id does not belong to the plan.")

    # ---- commit ----
    appt["status"] = "COMPLETED"
    touch(appt)
    auth = db.authorizations[appt["authorization_id"]]
    # reserved -1, committed +1 (recompute handles it); version increments.
    engine.reconcile_authorization(auth)

    # SessionNote created.
    note = new_record({
        "appointment_id": appt["id"],
        "narrative": narrative,
        "minutes_delivered": minutes_delivered,
        "goal_progress_entries": parsed_entries,
    })
    db.session_notes[note["id"]] = note

    # One GoalProgressEntry per item; recorded_session_time = appt.start_time.
    affected_goal_ids = set()
    for pe in parsed_entries:
        gpe = {
            "id": db.new_id(),
            "created_at": db.now_iso(),
            "goal_id": pe["goal_id"],
            "session_note_id": note["id"],
            "recorded_pct": pe["recorded_pct"],
            "recorded_session_time": appt["start_time"],
        }
        db.goal_progress_entries[gpe["id"]] = gpe
        affected_goal_ids.add(pe["goal_id"])

    # Recompute affected goals (chronological + MET/OPEN), then plan roll-up.
    for gid in affected_goal_ids:
        engine.reconcile_goal(db.goals[gid])
    plan = db.plans_of_care.get(plan_id)
    if plan is not None:
        engine.reconcile_plan_progress(plan)

    # Child active_appointment_count drops (SCHEDULED -> COMPLETED).
    child = db.children.get(appt["child_id"])
    if child is not None:
        engine.recompute_child(child)

    return success(serialize.appointment(appt), status=200)


@bp.route("/clinic/appointments/<appointment_id>/cancel", methods=["POST"])
@require_roles("ClinicAdmin", "SchedulingCoordinator")
def cancel(appointment_id, user_id=None, role=None):
    appt = lookup(db.appointments, appointment_id)
    if appt["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_APPOINTMENT_NOT_SCHEDULED, 409,
                       "Appointment must be SCHEDULED to cancel.")
    appt["status"] = "CANCELLED"
    touch(appt)
    auth = db.authorizations[appt["authorization_id"]]
    engine.reconcile_authorization(auth)
    child = db.children.get(appt["child_id"])
    if child is not None:
        engine.recompute_child(child)
    # Waitlist promotion runs for the therapist's freed slot.
    engine.run_waitlist_promotion(appt["therapist_id"])
    return success(serialize.appointment(appt), status=200)


@bp.route("/clinic/appointments/<appointment_id>/no-show", methods=["POST"])
@require_roles("ClinicAdmin", "SchedulingCoordinator")
def no_show(appointment_id, user_id=None, role=None):
    appt = lookup(db.appointments, appointment_id)
    if appt["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_APPOINTMENT_NOT_SCHEDULED, 409,
                       "Appointment must be SCHEDULED to record a no-show.")
    if db.clock.now() < parse_iso(appt["start_time"]):
        raise ApiError(errors.ERR_APPOINTMENT_IN_FUTURE, 409,
                       "Cannot record a no-show for a future appointment.")
    appt["status"] = "NO_SHOW"
    touch(appt)
    auth = db.authorizations[appt["authorization_id"]]
    engine.reconcile_authorization(auth)
    child = db.children.get(appt["child_id"])
    if child is not None:
        engine.recompute_child(child)
    # No waitlist promotion: the slot has already elapsed.
    return success(serialize.appointment(appt), status=200)
