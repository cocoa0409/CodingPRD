"""Sessions: booking, delivery, reschedule cycle (PRD §3.4, §2.9)."""
from datetime import timedelta

from flask import Blueprint, request

import calc
from auth import authenticate, require_role, require_ownership, body, get_int
from db import store
from engine import (session_overlap, check_enrollment_completion)
from envelope import success, success_list, paginate
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_COACH_NOT_CREDENTIALED, ERR_SESSION_OVERLAP,
                    ERR_OUTSIDE_PROGRAM_WINDOW, ERR_RESCHEDULE_CAP_REACHED,
                    ERR_NO_SESSIONS_REMAINING, not_found)
from serializers import session as ser_session, base_row, touch
from timeutil import parse_datetime, now

bp = Blueprint("sessions", __name__)


def _get_enrollment(eid):
    e = store.enrollments.get(eid)
    if e is None:
        raise not_found("Enrollment not found")
    return e


def _get_session(sid):
    s = store.sessions.get(sid)
    if s is None:
        raise not_found("Session not found")
    return s


def _inside_program_window(e, start):
    """Window: [activated_at, activated_at + duration_days) — half-open."""
    if e["activated_at"] is None:
        return False
    tier = store.tiers.get(e["program_tier_id"])
    close = e["activated_at"] + timedelta(days=tier["duration_days"])
    return e["activated_at"] <= start < close


@bp.post("/enrollments/<eid>/sessions")
def book_session(eid):
    role, uid = authenticate()
    require_role(role, uid, ("Client", "Coach"))
    e = _get_enrollment(eid)
    if role == "Client":
        require_ownership(e["client_id"], uid)
    else:
        require_ownership(e["coach_id"], uid)
    b = body()
    cohort_id = b.get("cohort_id")
    if cohort_id is not None and (not isinstance(cohort_id, str)
                                  or cohort_id not in store.cohorts):
        raise not_found("cohort_id does not reference an existing cohort")
    # Priority 4: parent lifecycle must be ACTIVE; DEFAULTED payment blocks booking.
    if e["lifecycle_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Sessions can only be booked under an ACTIVE enrollment")
    if e["payment_status"] == "DEFAULTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Session booking is blocked while payment is DEFAULTED")
    start = parse_datetime(b.get("scheduled_start"))
    duration = get_int(b, "duration_minutes")
    duration_ok = duration is not None and 30 <= duration <= 120
    # Priority 8: half-open, buffer-inclusive coach overlap.
    if start is not None and duration is not None and duration >= 1:
        if session_overlap(e["coach_id"], start, duration):
            raise ApiError(ERR_SESSION_OVERLAP, 409,
                           "Session collides with another SCHEDULED session for this coach")
    # Priority 10: program window.
    if start is not None and not _inside_program_window(e, start):
        raise ApiError(ERR_OUTSIDE_PROGRAM_WINDOW, 422,
                       "scheduled_start must lie inside [activated_at, activated_at + duration_days)")
    # Priority 12: session credit (booking allowed at exactly 1, rejected at 0).
    if calc.sessions_remaining(e) < 1:
        raise ApiError(ERR_NO_SESSIONS_REMAINING, 422, "No session credits remain")
    # Priority 20: request shape.
    if start is None or not duration_ok:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Required: scheduled_start (ISO 8601), duration_minutes 30..120")
    s = base_row()
    s.update({
        "enrollment_id": e["id"],
        "coach_id": e["coach_id"],
        "scheduled_start": start,
        "duration_minutes": duration,
        "buffer_minutes": calc.BUFFER_MINUTES,
        "session_status": "SCHEDULED",
        "successor_session_id": None,
        "is_late_reschedule": False,
        "cohort_id": cohort_id,
    })
    store.sessions[s["id"]] = s
    touch(e)  # sessions_remaining recomputed; enrollment version advances
    return success(ser_session(s)), 201


@bp.get("/sessions/<sid>")
def get_session(sid):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    return success(ser_session(_get_session(sid)))


@bp.get("/sessions")
def list_sessions():
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    rows = list(store.sessions.values())
    for param in ("enrollment_id", "coach_id", "session_status", "cohort_id",
                  "successor_session_id"):
        v = request.args.get(param)
        if v is not None:
            rows = [s for s in rows if s[param] == v]
    rows.sort(key=lambda s: (s["created_at"], s["_created_sort"]))
    page, meta = paginate(rows)
    return success_list([ser_session(s) for s in page], meta)


@bp.get("/enrollments/<eid>/sessions")
def list_enrollment_sessions(eid):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    _get_enrollment(eid)
    rows = [s for s in store.sessions.values() if s["enrollment_id"] == eid]
    rows.sort(key=lambda s: (s["created_at"], s["_created_sort"]))
    page, meta = paginate(rows)
    return success_list([ser_session(s) for s in page], meta)


@bp.post("/sessions/<sid>/complete")
def complete_session(sid):
    role, uid = authenticate()
    require_role(role, uid, ("Coach",))
    s = _get_session(sid)
    require_ownership(s["coach_id"], uid)
    e = store.enrollments.get(s["enrollment_id"])
    # Priority 4 state checks precede the priority 6 credential gate.
    if s["session_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SCHEDULED session can be completed")
    if e is None or e["lifecycle_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Completion requires the enrollment to be ACTIVE")
    if e["payment_status"] == "DEFAULTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Session completion is blocked while payment is DEFAULTED")
    if now() < s["scheduled_start"]:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "The current time has not reached the scheduled start")
    coach = store.coaches.get(s["coach_id"])
    if (coach is None or coach["credential_status"] != "VERIFIED"
            or coach["ethics_status"] != "ACTIVE"):
        raise ApiError(ERR_COACH_NOT_CREDENTIALED, 422,
                       "Coach is not delivery-eligible (credential VERIFIED and ethics ACTIVE required)")
    s["session_status"] = "COMPLETED"
    touch(s)
    touch(e)  # sessions_consumed recomputed; enrollment version advances
    check_enrollment_completion(e)  # possible ACTIVE -> COMPLETED bubble-up
    # Client engagement_score recomputes (computed at read time).
    return success(ser_session(s))


@bp.post("/sessions/<sid>/mark-no-show")
def no_show_session(sid):
    role, uid = authenticate()
    require_role(role, uid, ("Coach",))
    s = _get_session(sid)
    require_ownership(s["coach_id"], uid)
    if s["session_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SCHEDULED session can be marked NO_SHOW")
    if now() < s["scheduled_start"] + timedelta(minutes=s["duration_minutes"]):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "The session window (start + duration) has not yet passed")
    s["session_status"] = "NO_SHOW"  # consumes a session credit
    touch(s)
    e = store.enrollments.get(s["enrollment_id"])
    if e is not None:
        touch(e)  # sessions_consumed recomputed
        check_enrollment_completion(e)
    return success(ser_session(s))


@bp.post("/sessions/<sid>/cancel")
def cancel_session(sid):
    role, uid = authenticate()
    require_role(role, uid, ("Client",))
    s = _get_session(sid)
    e = store.enrollments.get(s["enrollment_id"])
    require_ownership(e["client_id"] if e is not None else None, uid)
    if s["session_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SCHEDULED session can be cancelled")
    s["session_status"] = "CANCELLED"  # does NOT consume a credit
    touch(s)
    if e is not None:
        touch(e)  # sessions_remaining recomputed; enrollment version advances
    return success(ser_session(s))


@bp.post("/sessions/<sid>/reschedule")
def reschedule_session(sid):
    """Cancellation-plus-successor: the old session becomes CANCELLED with
    successor_session_id pointing at the newly created SCHEDULED session.
    Timing against the ORIGINAL start decides cost: >= 24h ahead is free
    (exactly 24h, to the second, is free); strictly inside is counted against
    the tier's reschedule_cap (PRD §3.4, calc reschedule_policy_gate)."""
    role, uid = authenticate()
    require_role(role, uid, ("Client",))
    s = _get_session(sid)
    e = store.enrollments.get(s["enrollment_id"])
    require_ownership(e["client_id"] if e is not None else None, uid)
    if s["session_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SCHEDULED session can be rescheduled")
    if e is None or e["lifecycle_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Reschedule requires the enrollment to be ACTIVE")
    b = body()
    start = parse_datetime(b.get("scheduled_start"))
    duration = get_int(b, "duration_minutes")
    duration_ok = duration is not None and 30 <= duration <= 120
    # Priority 8: overlap on the NEW interval (the old session is excluded).
    if start is not None and duration is not None and duration >= 1:
        if session_overlap(s["coach_id"], start, duration, exclude_session_id=s["id"]):
            raise ApiError(ERR_SESSION_OVERLAP, 409,
                           "Session collides with another SCHEDULED session for this coach")
    # Priority 10: program window on the new start.
    if start is not None and not _inside_program_window(e, start):
        raise ApiError(ERR_OUTSIDE_PROGRAM_WINDOW, 422,
                       "scheduled_start must lie inside [activated_at, activated_at + duration_days)")
    # Priority 11: late-reschedule cap (strictly inside 24h is counted).
    seconds_before_start = (s["scheduled_start"] - now()).total_seconds()
    is_late = seconds_before_start < calc.RESCHEDULE_FREE_HOURS * 3600
    tier = store.tiers.get(e["program_tier_id"])
    if is_late and e["late_reschedules_used"] >= tier["reschedule_cap"]:
        raise ApiError(ERR_RESCHEDULE_CAP_REACHED, 422,
                       "Late reschedule cap reached for this enrollment's tier")
    # Priority 20: request shape.
    if start is None or not duration_ok:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Required: scheduled_start (ISO 8601), duration_minutes 30..120")
    new = base_row()
    new.update({
        "enrollment_id": s["enrollment_id"],
        "coach_id": s["coach_id"],
        "scheduled_start": start,
        "duration_minutes": duration,
        "buffer_minutes": calc.BUFFER_MINUTES,
        "session_status": "SCHEDULED",
        "successor_session_id": None,
        "is_late_reschedule": is_late,
        "cohort_id": s["cohort_id"],
    })
    store.sessions[new["id"]] = new
    s["session_status"] = "CANCELLED"
    s["successor_session_id"] = new["id"]
    touch(s)
    if is_late:
        e["late_reschedules_used"] += 1
        touch(e)
    return success(ser_session(new))
