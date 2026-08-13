"""Orientation appointments: scheduling, lifecycle, checklist (PRD §3.2/§3.3)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from db import appointments, attendees, communities, homes, reps
from errors import (
    err_attendee_requirement, err_checklist_incomplete, err_invalid_state,
    err_not_found, err_referenced_entity_not_found, err_rep_inactive,
    err_reschedule_limit, err_stale_version, err_start_window,
)
from logic import (
    APPOINTMENT_START_EARLY_MINUTES, RESCHEDULE_LIMIT, appointment_window_check,
    completion_cascade, open_appointment_check, orientation_overlap_check,
    seed_checklist, checklist_counts,
)
from middleware import ROLE_BUYER, ROLE_MANAGER, ROLE_REP, require_roles
from response import paginate, success_list, success_object
from validation import (
    json_body, opt_enum, opt_int, req_datetime_str, req_enum, req_str, req_version,
)

bp = Blueprint("appointments", __name__)

READ_ROLES = (ROLE_MANAGER, ROLE_REP, ROLE_BUYER)
CANCEL_REASONS = ("BUYER_NO_SHOW", "BUYER_REQUEST", "BUILDER_DELAY")
CHECKLIST_OUTCOMES = ("DEMONSTRATED", "SKIPPED", "PENDING")


def _get_appt_or_404(appointment_id):
    appt = appointments.get(appointment_id)
    if appt is None:
        raise err_not_found("Appointment %s not found." % appointment_id)
    return appt


@bp.post("/api/appointments")
def create_appointment():
    require_roles(ROLE_REP)
    body = json_body()
    home_id = req_str(body, "home_id")
    rep_id = req_str(body, "rep_id")
    scheduled_start = req_datetime_str(body, "scheduled_start")
    duration = opt_int(body, "duration_minutes", minimum=1)

    home = homes.get(home_id)
    rep = reps.get(rep_id)
    if home is None or rep is None:
        raise err_referenced_entity_not_found("home_id or rep_id does not resolve.")
    community = communities[home["community_id"]]
    if duration is None:
        duration = community["appointment_duration_minutes"]
    start_dt = db.parse_dt(scheduled_start)

    # state gate: first orientation from PRE_CLOSE_READY, re-orientation from ORIENTED
    if home["status"] not in ("PRE_CLOSE_READY", "ORIENTED"):
        raise err_invalid_state("The home is not ready for orientation scheduling.")
    # temporal gates: schedule-in-past, then closing window
    appointment_window_check(home, community, start_dt)
    # structural gates
    if not rep["active"]:
        raise err_rep_inactive()
    open_appointment_check(home_id)
    orientation_overlap_check(rep_id, community, start_dt, duration)

    rec = db.stamp({
        "id": db.new_id(),
        "home_id": home_id,
        "rep_id": rep_id,
        "scheduled_start": scheduled_start,
        "duration_minutes": duration,
        "status": "REQUESTED",
        "reschedule_count": 0,
        "cancel_reason": None,
        "completed_at": None,
        "checklist_items": [],
        "checklist_total_count": 0,
        "checklist_demonstrated_count": 0,
        "checklist_pending_count": 0,
        "checklist_skipped_count": 0,
    })
    appointments[rec["id"]] = rec
    return success_object(db.public(rec), status=201)


@bp.get("/api/appointments/<appointment_id>")
def get_appointment(appointment_id):
    require_roles(*READ_ROLES)
    return success_object(db.public(_get_appt_or_404(appointment_id)))


@bp.get("/api/appointments")
def list_appointments():
    require_roles(*READ_ROLES)
    items = list(appointments.values())
    for f in ("home_id", "rep_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    items.sort(key=db.sort_key)
    page, pagination = paginate(items, request.args)
    return success_list([db.public(a) for a in page], pagination)


@bp.post("/api/appointments/<appointment_id>/confirm")
def confirm_appointment(appointment_id):
    require_roles(ROLE_MANAGER)
    appt = _get_appt_or_404(appointment_id)
    if appt["status"] != "REQUESTED":
        raise err_invalid_state("Only a REQUESTED appointment can be confirmed.")
    appt["status"] = "CONFIRMED"
    db.touch(appt)
    home = homes[appt["home_id"]]
    if home["status"] in ("PRE_CLOSE_READY", "ORIENTED"):
        home["status"] = "ORIENTATION_SCHEDULED"
        db.touch(home)
    return success_object(db.public(appt))


@bp.post("/api/appointments/<appointment_id>/reschedule")
def reschedule_appointment(appointment_id):
    require_roles(ROLE_REP)
    body = json_body()
    scheduled_start = req_datetime_str(body, "scheduled_start")
    duration = opt_int(body, "duration_minutes", minimum=1)
    expected = req_version(body, "expected_appointment_version")

    appt = _get_appt_or_404(appointment_id)
    if appt["status"] not in ("REQUESTED", "CONFIRMED"):
        raise err_invalid_state("Only a REQUESTED or CONFIRMED appointment can be rescheduled.")
    if expected != appt["version"]:
        raise err_stale_version("expected_appointment_version does not match the appointment's current version.")

    home = homes[appt["home_id"]]
    community = communities[home["community_id"]]
    new_duration = appt["duration_minutes"] if duration is None else duration
    start_dt = db.parse_dt(scheduled_start)

    # temporal gates: schedule-in-past, then closing window
    appointment_window_check(home, community, start_dt)
    # structural gates: reschedule cap, then buffered overlap
    if appt["reschedule_count"] >= RESCHEDULE_LIMIT:
        raise err_reschedule_limit()
    orientation_overlap_check(appt["rep_id"], community, start_dt, new_duration,
                              exclude_id=appt["id"])

    appt["scheduled_start"] = scheduled_start
    appt["duration_minutes"] = new_duration
    appt["reschedule_count"] += 1
    db.touch(appt)
    return success_object(db.public(appt))


@bp.post("/api/appointments/<appointment_id>/cancel")
def cancel_appointment(appointment_id):
    require_roles(ROLE_REP, ROLE_MANAGER)
    body = json_body()
    reason = opt_enum(body, "reason", CANCEL_REASONS)
    appt = _get_appt_or_404(appointment_id)
    if appt["status"] not in ("REQUESTED", "CONFIRMED"):
        raise err_invalid_state("Only a REQUESTED or CONFIRMED appointment can be cancelled.")
    if appt["status"] == "REQUESTED":
        if reason == "BUYER_NO_SHOW":
            raise err_invalid_state("A REQUESTED appointment cannot be marked NO_SHOW.")
        appt["status"] = "CANCELLED"
    else:  # CONFIRMED
        if reason == "BUYER_NO_SHOW":
            appt["status"] = "NO_SHOW"
        else:
            appt["status"] = "CANCELLED"
        home = homes[appt["home_id"]]
        if home["status"] == "ORIENTATION_SCHEDULED":
            home["status"] = "PRE_CLOSE_READY"
            db.touch(home)
    appt["cancel_reason"] = reason
    db.touch(appt)
    return success_object(db.public(appt))


@bp.post("/api/appointments/<appointment_id>/start")
def start_appointment(appointment_id):
    require_roles(ROLE_REP)
    appt = _get_appt_or_404(appointment_id)
    if appt["status"] != "CONFIRMED":
        raise err_invalid_state("Only a CONFIRMED appointment can be started.")
    start_dt = db.parse_dt(appt["scheduled_start"])
    now = db.now()
    window_open = start_dt - timedelta(minutes=APPOINTMENT_START_EARLY_MINUTES)
    window_close = start_dt + timedelta(minutes=appt["duration_minutes"])
    if not (window_open <= now <= window_close):
        raise err_start_window()
    appt["status"] = "IN_PROGRESS"
    seed_checklist(appt)
    db.touch(appt)
    return success_object(db.public(appt))


@bp.post("/api/appointments/<appointment_id>/complete")
def complete_appointment(appointment_id):
    require_roles(ROLE_REP)
    appt = _get_appt_or_404(appointment_id)
    if appt["status"] != "IN_PROGRESS":
        raise err_invalid_state("Only an IN_PROGRESS appointment can be completed.")
    # Gate 1: every required checklist entry DEMONSTRATED and no entry PENDING.
    checklist_ok = all(
        entry["demonstration_status"] != "PENDING"
        and (not entry["is_required"] or entry["demonstration_status"] == "DEMONSTRATED")
        for entry in appt["checklist_items"]
    )
    if not checklist_ok:
        raise err_checklist_incomplete()
    # Gate 2: a VERIFIED attendee covering the primary buyer (direct or POA proxy).
    home = homes[appt["home_id"]]
    covered = any(
        a["verification_status"] == "VERIFIED" and (
            (a["attendee_type"] in ("BUYER", "CO_BUYER")
             and a.get("buyer_id") == home["primary_buyer_id"])
            or a["attendee_type"] == "POA_PROXY"
        )
        for a in attendees.values()
        if a["appointment_id"] == appt["id"]
    )
    if not covered:
        raise err_attendee_requirement()
    completion_cascade(appt, home)
    return success_object(db.public(appt))


@bp.post("/api/appointments/<appointment_id>/checklist-items/<system_key>/mark")
def mark_checklist_item(appointment_id, system_key):
    require_roles(ROLE_REP)
    body = json_body()
    outcome = req_enum(body, "outcome", CHECKLIST_OUTCOMES)
    # Path identifiers resolve left to right: appointment, then system_key.
    appt = _get_appt_or_404(appointment_id)
    entry = next(
        (e for e in appt["checklist_items"] if e["system_key"] == system_key), None
    )
    if entry is None:
        raise err_not_found("Checklist entry %s not found." % system_key)
    if appt["status"] != "IN_PROGRESS":
        raise err_invalid_state("Checklist entries can only be marked while IN_PROGRESS.")
    entry["demonstration_status"] = outcome
    entry["demonstrated_at"] = db.fmt_dt(db.now()) if outcome == "DEMONSTRATED" else None
    checklist_counts(appt)
    db.touch(appt)
    return success_object(db.public(appt))
