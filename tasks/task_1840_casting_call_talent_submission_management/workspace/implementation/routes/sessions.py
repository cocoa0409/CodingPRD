"""AuditionSession and CallbackAppointment endpoints."""
from flask import Blueprint, request

import db
from errors import (err_invalid_request, err_invalid_state, err_not_found,
                    err_ref_not_found, err_session_full, err_slot_outside,
                    err_talent_conflict, err_unauthorized)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from util import (check_datetime, check_int, check_string, filter_status,
                  get_payload, new_record, paginate, parse_dt, serialize, touch)

S = db.STORE
bp = Blueprint("sessions", __name__)

READ_ROLES = ("CastingDirector", "CastingAssociate", "ProductionCoordinator", "Agent")


def _get_breakdown(bid):
    b = domain.find("breakdowns", bid)
    if b is None:
        raise err_not_found("Breakdown not found")
    return b


def _get_session(sid):
    s = domain.find("sessions", sid)
    if s is None:
        raise err_not_found("AuditionSession not found")
    return s


def _get_appointment(aid):
    a = domain.find("appointments", aid)
    if a is None:
        raise err_not_found("CallbackAppointment not found")
    return a


def _check_appointment_actor(user_id, role, submission):
    """Confirm/decline ownership: the submission's agent, or a CastingAssociate
    standing in for a self-submission."""
    if role == "Agent":
        if submission.get("agent_id") != user_id:
            raise err_unauthorized("Only the submission's agent may perform this action")
    elif role == "CastingAssociate":
        if submission.get("agent_id") is not None:
            raise err_unauthorized("CastingAssociate may act only on self-submissions")


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@bp.post("/casting/breakdowns/<bid>/sessions")
def create_session(bid):
    require_roles("CastingAssociate")
    _get_breakdown(bid)
    body = get_payload()
    rec = new_record({
        "breakdown_id": bid,
        "session_start": parse_dt(body.get("session_start")) if body.get("session_start") is not None else None,
        "session_end": parse_dt(body.get("session_end")) if body.get("session_end") is not None else None,
        "capacity": body.get("capacity"),
        "location": body.get("location"),
        "status": "SCHEDULED",
        "booked_count": 0,
    })
    start = check_datetime(body, "session_start")
    end = check_datetime(body, "session_end")
    if not end > start:
        raise err_invalid_request("session_end must be strictly after session_start")
    check_int(body, "capacity", min_v=1)
    check_string(body, "location")
    S["sessions"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.get("/casting/sessions/<sid>")
def get_session(sid):
    require_roles(*READ_ROLES)
    return success_object(serialize(_get_session(sid)))


@bp.get("/casting/breakdowns/<bid>/sessions")
def list_sessions(bid):
    require_roles(*READ_ROLES)
    _get_breakdown(bid)
    records = filter_status(domain.children("sessions", "breakdown_id", bid))
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.post("/casting/sessions/<sid>/complete")
def complete_session(sid):
    require_roles("CastingAssociate")
    sess = _get_session(sid)
    if sess["status"] != "IN_PROGRESS":
        raise err_invalid_state("Only an IN_PROGRESS session can be completed")
    if any(a["session_id"] == sid and a["status"] == "PROPOSED"
           for a in S["appointments"].values()):
        raise err_invalid_state("All PROPOSED appointments must be resolved before completion")
    for a in S["appointments"].values():
        if a["session_id"] == sid and a["status"] == "CONFIRMED" and not a.get("_completed"):
            a["status"] = "NO_SHOW"
            touch(a)
    sess["status"] = "COMPLETED"
    domain.recompute_booked_count(sess, bump=False)
    touch(sess)
    return success_object(serialize(sess))


@bp.post("/casting/sessions/<sid>/cancel")
def cancel_session(sid):
    require_roles("CastingAssociate")
    sess = _get_session(sid)
    if sess["status"] != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED session can be cancelled")
    affected_submissions = set()
    for a in S["appointments"].values():
        if a["session_id"] == sid and a["status"] in ("PROPOSED", "CONFIRMED"):
            a["status"] = "CANCELLED"
            touch(a)
            affected_submissions.add(a["submission_id"])
    sess["status"] = "CANCELLED"
    domain.recompute_booked_count(sess, bump=False)
    touch(sess)
    for sub_id in affected_submissions:
        sub = domain.find("submissions", sub_id)
        if sub is not None:
            domain.revert_submission_if_no_active_appointments(sub)
    return success_object(serialize(sess))


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------

@bp.post("/casting/sessions/<sid>/appointments")
def create_appointment(sid):
    require_roles("CastingAssociate")
    sess = _get_session(sid)
    body = get_payload()
    sub = None
    if body.get("submission_id") is not None:
        sub = domain.find("submissions", body.get("submission_id"))
        if sub is None:
            raise err_ref_not_found("submission_id does not reference a Submission")
    # State-machine legality: submission must be SHORTLISTED
    if sub is not None and sub["status"] != "SHORTLISTED":
        raise err_invalid_state("Callback appointments require a SHORTLISTED submission")
    # Slot must fit inside the session window (half-open [start, end))
    slot_start = parse_dt(body.get("slot_start")) if body.get("slot_start") is not None else None
    slot_end = parse_dt(body.get("slot_end")) if body.get("slot_end") is not None else None
    if slot_start is not None and slot_end is not None:
        if not (sess["session_start"] <= slot_start < slot_end <= sess["session_end"]):
            raise err_slot_outside()
    # Final field validation
    check_string(body, "submission_id")
    slot_start = check_datetime(body, "slot_start")
    slot_end = check_datetime(body, "slot_end")
    buffer_minutes = check_int(body, "buffer_minutes", required=False, default=0, min_v=0)
    rec = new_record({
        "session_id": sid,
        "submission_id": sub["id"],
        "slot_start": slot_start,
        "slot_end": slot_end,
        "status": "PROPOSED",
        "buffer_minutes": buffer_minutes,
        "_completed": False,
    })
    S["appointments"][rec["id"]] = rec
    sub["status"] = "CALLBACK_INVITED"
    touch(sub)
    return success_object(serialize(rec), 201)


@bp.get("/casting/appointments/<aid>")
def get_appointment(aid):
    require_roles(*READ_ROLES)
    return success_object(serialize(_get_appointment(aid)))


@bp.get("/casting/sessions/<sid>/appointments")
def list_session_appointments(sid):
    require_roles(*READ_ROLES)
    _get_session(sid)
    records = filter_status(domain.children("appointments", "session_id", sid))
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/casting/submissions/<sid>/appointments")
def list_submission_appointments(sid):
    require_roles(*READ_ROLES)
    if domain.find("submissions", sid) is None:
        raise err_not_found("Submission not found")
    records = filter_status(domain.children("appointments", "submission_id", sid))
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.post("/casting/appointments/<aid>/confirm")
def confirm_appointment(aid):
    user_id, role = require_roles("Agent", "CastingAssociate")
    appt = _get_appointment(aid)
    sub = domain.find("submissions", appt["submission_id"])
    _check_appointment_actor(user_id, role, sub)
    if appt["status"] != "PROPOSED":
        raise err_invalid_state("Only a PROPOSED appointment can be confirmed")
    sess = domain.find("sessions", appt["session_id"])
    # 1) talent-conflict check (buffer applied to the NEW appointment's tail)
    if domain.appointment_conflicts(appt, sub["talent_id"]):
        raise err_talent_conflict()
    # 2) capacity check
    domain.recompute_booked_count(sess, bump=False)
    if sess["booked_count"] >= sess["capacity"]:
        raise err_session_full()
    appt["status"] = "CONFIRMED"
    touch(appt)
    domain.recompute_booked_count(sess, bump=True)
    return success_object(serialize(appt))


@bp.post("/casting/appointments/<aid>/decline")
def decline_appointment(aid):
    user_id, role = require_roles("Agent", "CastingAssociate")
    appt = _get_appointment(aid)
    sub = domain.find("submissions", appt["submission_id"])
    _check_appointment_actor(user_id, role, sub)
    if appt["status"] != "PROPOSED":
        raise err_invalid_state("Only a PROPOSED appointment can be declined")
    appt["status"] = "DECLINED"
    touch(appt)
    domain.revert_submission_if_no_active_appointments(sub)
    return success_object(serialize(appt))


@bp.post("/casting/appointments/<aid>/cancel")
def cancel_appointment(aid):
    require_roles("CastingAssociate")
    appt = _get_appointment(aid)
    if appt["status"] not in ("PROPOSED", "CONFIRMED"):
        raise err_invalid_state("Only PROPOSED or CONFIRMED appointments can be cancelled")
    sub = domain.find("submissions", appt["submission_id"])
    sess = domain.find("sessions", appt["session_id"])
    appt["status"] = "CANCELLED"
    touch(appt)
    if sess is not None:
        domain.recompute_booked_count(sess, bump=True)
    if sub is not None:
        domain.revert_submission_if_no_active_appointments(sub)
    return success_object(serialize(appt))


@bp.post("/casting/appointments/<aid>/complete")
def complete_appointment(aid):
    require_roles("CastingAssociate")
    appt = _get_appointment(aid)
    sub = domain.find("submissions", appt["submission_id"])
    if appt["status"] not in ("PROPOSED", "CONFIRMED") or appt.get("_completed"):
        raise err_invalid_state("Appointment cannot be completed from its current state")
    if sub is None or sub["status"] != "CALLBACK_INVITED":
        raise err_invalid_state("Submission must be CALLBACK_INVITED to complete an appointment")
    sess = domain.find("sessions", appt["session_id"])
    appt["_completed"] = True
    touch(appt)
    if sess is not None:
        # booked_count drops by one when the appointment had been CONFIRMED;
        # per PRD 3.5 the session version is NOT bumped by appointment completion.
        domain.recompute_booked_count(sess, bump=False)
    sub["status"] = "CALLBACK_COMPLETED"
    touch(sub)
    return success_object(serialize(appt))
