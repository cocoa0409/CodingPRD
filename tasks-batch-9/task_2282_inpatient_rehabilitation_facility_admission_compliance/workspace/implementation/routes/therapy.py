"""Therapy measurement: weeks, sessions and the three-hour rule (PRD §3.6)."""

from datetime import timedelta

from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from db import store
from errors import ApiError
from queryargs import date_arg, enum_arg, int_arg, matches, str_arg
from response import envelope, paged, pagination_params
from services import (DISCIPLINE_CREDENTIAL, DISCIPLINES, MODALITIES, active_plan,
                      by_seq, credited_minutes_for, propagate_admission,
                      refresh_week_counters, require, sessions_of_admission, stamp_new,
                      touch, week_verdict, weeks_of)
from util import Body, add_days, date_of, dt_of, iso, parse_date, serialize

bp = Blueprint("therapy", __name__)

WEEK_STATUSES = ("OPEN", "MET", "NOT_MET", "EXCEPTION_GRANTED")
SESSION_STATUSES = ("SCHEDULED", "DELIVERED", "VOIDED")
REST_BUFFER = timedelta(minutes=10)


def _sync_week(week):
    """Refresh counters and re-evaluate a MET / NOT_MET week (PRD §3.6)."""
    changed = refresh_week_counters(week)
    if week["status"] in ("MET", "NOT_MET"):
        verdict = week_verdict(week)
        if verdict != week["status"]:
            week["status"] = verdict
            changed = True
    if changed:
        touch(week)
    return changed


# =============================================================== therapy weeks ===
@bp.post("/therapy-weeks")
def create_week():
    authenticate(("TherapyLead",))
    body = Body(request.get_json(silent=True))

    admission_id = body.id_field("admission_id")
    week_index = body.int_field("week_index", minimum=1, maximum=26)
    week_start = body.date_field("week_start_date")
    week_end = add_days(week_start, 6)

    # ladder rank 10 — body identifier existence
    admission = require(store.admissions, admission_id)

    # ladder rank 17 — the stay must be active
    if admission["stay_status"] != "ADMITTED":
        raise ApiError("ERR_ADMISSION_NOT_ACTIVE")

    # ladder rank 26 — an ACTIVE plan of care must exist
    plan = active_plan(admission_id)
    if plan is None:
        raise ApiError("ERR_PLAN_OF_CARE_MISSING")

    existing = weeks_of(admission_id)

    # ladder rank 35 — windows may touch but not overlap
    for other in existing:
        other_start = parse_date(other["week_start_date"])
        other_end = parse_date(other["week_end_date"])
        if week_start <= other_end and other_start <= week_end:
            raise ApiError("ERR_THERAPY_WEEK_OVERLAP")

    # ladder rank 36 — the window may not start before the admit date
    admitted_date = date_of(admission["admitted_at"])
    if admitted_date is not None and week_start < admitted_date:
        raise ApiError("ERR_WEEK_BEFORE_ADMISSION")

    # ladder rank 39 — week_index unique per admission
    for other in existing:
        if other["week_index"] == week_index:
            raise ApiError("ERR_WEEK_INDEX_DUPLICATE")

    week = stamp_new({
        "admission_id": admission_id,
        "exception_granted_by_clinician_id": None,
        "week_index": week_index,
        "week_start_date": week_start.isoformat(),
        "week_end_date": week_end.isoformat(),
        "evaluation_mode": plan["three_hour_rule_mode"],
        "delivered_credited_minutes": 0,
        "qualifying_days_count": 0,
        "exception_reason": None,
        "status": "OPEN",
    })
    store.weeks[week["id"]] = week
    return envelope(serialize(week), 201)


@bp.get("/therapy-weeks/<week_id>")
def get_week(week_id):
    authenticate(ALL_ROLES)
    week = require(store.weeks, week_id)
    return envelope(serialize(week), 200)


@bp.get("/therapy-weeks")
def list_weeks():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    filters = {
        "admission_id": str_arg("admission_id"),
        "exception_granted_by_clinician_id": str_arg("exception_granted_by_clinician_id"),
        "status": enum_arg("status", WEEK_STATUSES),
        "week_index": int_arg("week_index"),
    }
    items = [w for w in by_seq(list(store.weeks.values())) if matches(w, filters)]
    page, pagination = paged(items, limit, offset)
    return envelope([serialize(w) for w in page], 200, pagination)


@bp.post("/therapy-weeks/<week_id>/evaluate")
def evaluate_week(week_id):
    authenticate(("TherapyLead",))
    week = require(store.weeks, week_id)

    # ladder rank 16 — explicit evaluation is declared only from OPEN
    if week["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")

    # ladder rank 26 — an ACTIVE plan of care must exist
    if active_plan(week["admission_id"]) is None:
        raise ApiError("ERR_PLAN_OF_CARE_MISSING")

    refresh_week_counters(week)
    week["status"] = week_verdict(week)
    touch(week)

    admission = store.admissions.get(week["admission_id"])
    if admission is not None:
        propagate_admission(admission)
    return envelope(serialize(week), 200)


@bp.post("/therapy-weeks/<week_id>/exception")
def grant_exception(week_id):
    user_id, _ = authenticate(("RehabPhysician",))
    body = Body(request.get_json(silent=True))
    exception_reason = body.str_field("exception_reason", min_len=1)

    week = require(store.weeks, week_id)

    # ladder rank 19 — an exception is only available to a failed week
    if week["status"] != "NOT_MET":
        raise ApiError("ERR_EXCEPTION_NOT_ALLOWED")

    week["status"] = "EXCEPTION_GRANTED"
    week["exception_reason"] = exception_reason
    week["exception_granted_by_clinician_id"] = user_id
    touch(week)

    admission = store.admissions.get(week["admission_id"])
    if admission is not None:
        propagate_admission(admission)
    return envelope(serialize(week), 200)


# ============================================================ therapy sessions ===
@bp.post("/therapy-sessions")
def create_session():
    authenticate(("TherapyLead",))
    body = Body(request.get_json(silent=True))

    admission_id = body.id_field("admission_id")
    clinician_id = body.id_field("clinician_id")
    discipline = body.enum_field("discipline", DISCIPLINES)
    modality = body.enum_field("modality", MODALITIES)
    start_at = body.dt_field("start_at")
    end_at = body.dt_field("end_at")
    group_size = body.int_field("group_size", required=False, default=1)

    # ladder rank 6 — session interval sanity
    if end_at <= start_at:
        raise ApiError("ERR_INVALID_SESSION_INTERVAL")
    raw_minutes = int((end_at - start_at).total_seconds()) // 60
    if raw_minutes < 1:
        raise ApiError("ERR_INVALID_SESSION_INTERVAL")

    # ladder rank 7 — modality / group size coherence
    if modality == "INDIVIDUAL" and group_size != 1:
        raise ApiError("ERR_GROUP_SIZE_INVALID")
    if modality == "CONCURRENT" and group_size != 2:
        raise ApiError("ERR_GROUP_SIZE_INVALID")
    if modality == "GROUP" and not 3 <= group_size <= 6:
        raise ApiError("ERR_GROUP_SIZE_INVALID")

    # ladder rank 10 — body identifier existence
    admission = require(store.admissions, admission_id)
    clinician = require(store.clinicians, clinician_id)

    # ladder rank 13 — facility boundary
    if clinician["facility_id"] != admission["facility_id"]:
        raise ApiError("ERR_CROSS_FACILITY_MISMATCH")

    # ladder rank 17 — the stay must be active
    if admission["stay_status"] != "ADMITTED":
        raise ApiError("ERR_ADMISSION_NOT_ACTIVE")

    # ladder rank 26 — an ACTIVE plan of care must exist
    plan = active_plan(admission_id)
    if plan is None:
        raise ApiError("ERR_PLAN_OF_CARE_MISSING")

    # ladder rank 27 — the discipline must be in the plan
    if discipline not in plan["disciplines"]:
        raise ApiError("ERR_DISCIPLINE_NOT_IN_PLAN")

    # ladder rank 28 — credential must match the discipline exactly
    if clinician["credential"] != DISCIPLINE_CREDENTIAL[discipline]:
        raise ApiError("ERR_CLINICIAN_DISCIPLINE_MISMATCH")

    live_statuses = ("SCHEDULED", "DELIVERED")

    # ladder rank 32 — the treating clinician may not be double-booked
    for other in by_seq(list(store.sessions.values())):
        if other["clinician_id"] != clinician_id or other["status"] not in live_statuses:
            continue
        other_start = dt_of(other["start_at"])
        other_end = dt_of(other["end_at"])
        if start_at < other_end and other_start < end_at:
            raise ApiError("ERR_CLINICIAN_SCHEDULE_CONFLICT")

    # ladder rank 33 — the patient's ten-minute rest buffer
    for other in sessions_of_admission(admission_id):
        if other["status"] not in live_statuses:
            continue
        other_start = dt_of(other["start_at"])
        other_end = dt_of(other["end_at"])
        if start_at < other_end + REST_BUFFER and other_start < end_at + REST_BUFFER:
            raise ApiError("ERR_PATIENT_REST_BUFFER_VIOLATION")

    # ladder rank 34 — the session date must fall inside a week window
    session_date = start_at.date()
    session_date_str = session_date.isoformat()
    candidates = [w for w in weeks_of(admission_id)
                  if w["week_start_date"] <= session_date_str <= w["week_end_date"]]
    if not candidates:
        raise ApiError("ERR_NO_OPEN_THERAPY_WEEK")
    week = candidates[0]

    credited_minutes = credited_minutes_for(modality, raw_minutes, group_size)

    # ladder rank 46 — the facility's daily credited-minute ceiling
    facility = store.facilities.get(admission["facility_id"])
    if facility is not None:
        booked = sum(s["credited_minutes"] for s in sessions_of_admission(admission_id)
                     if s["status"] in live_statuses and s["session_date"] == session_date_str)
        if booked + credited_minutes > facility["daily_therapy_cap_minutes"]:
            raise ApiError("ERR_DAILY_THERAPY_CAP_EXCEEDED")

    session = stamp_new({
        "admission_id": admission_id,
        "therapy_week_id": week["id"],
        "clinician_id": clinician_id,
        "discipline": discipline,
        "modality": modality,
        "group_size": group_size,
        "start_at": iso(start_at),
        "end_at": iso(end_at),
        "session_date": session_date_str,
        "raw_minutes": raw_minutes,
        "credited_minutes": credited_minutes,
        "documented_at": None,
        "void_reason": None,
        "status": "SCHEDULED",
    })
    store.sessions[session["id"]] = session
    return envelope(serialize(session), 201)


@bp.get("/therapy-sessions/<session_id>")
def get_session(session_id):
    authenticate(ALL_ROLES)
    session = require(store.sessions, session_id)
    return envelope(serialize(session), 200)


@bp.get("/therapy-sessions")
def list_sessions():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    filters = {
        "admission_id": str_arg("admission_id"),
        "therapy_week_id": str_arg("therapy_week_id"),
        "clinician_id": str_arg("clinician_id"),
        "status": enum_arg("status", SESSION_STATUSES),
        "session_date": date_arg("session_date"),
    }
    items = [s for s in by_seq(list(store.sessions.values())) if matches(s, filters)]
    page, pagination = paged(items, limit, offset)
    return envelope([serialize(s) for s in page], 200, pagination)


@bp.post("/therapy-sessions/<session_id>/deliver")
def deliver_session(session_id):
    authenticate(("TherapyLead",))
    session = require(store.sessions, session_id)

    # ladder rank 16 — declared transition SCHEDULED -> DELIVERED
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")

    admission = store.admissions.get(session["admission_id"])
    # ladder rank 17 — the stay must be active
    if admission is None or admission["stay_status"] != "ADMITTED":
        raise ApiError("ERR_ADMISSION_NOT_ACTIVE")

    # the treating clinician must still be ACTIVE (PRD §3.6)
    treating = store.clinicians.get(session["clinician_id"])
    if treating is None or treating["status"] != "ACTIVE":
        raise ApiError("ERR_ACTING_CLINICIAN_INACTIVE")

    session["status"] = "DELIVERED"
    session["documented_at"] = iso(store.clock)
    touch(session)

    week = store.weeks.get(session["therapy_week_id"])
    if week is not None:
        _sync_week(week)
    propagate_admission(admission)

    return envelope(serialize(session), 200)


@bp.post("/therapy-sessions/<session_id>/void")
def void_session(session_id):
    authenticate(("TherapyLead",))
    body = Body(request.get_json(silent=True))
    void_reason = body.str_field("void_reason", min_len=1)

    session = require(store.sessions, session_id)

    # ladder rank 16 — declared from SCHEDULED and from DELIVERED
    if session["status"] not in ("SCHEDULED", "DELIVERED"):
        raise ApiError("ERR_INVALID_STATE")

    was_delivered = session["status"] == "DELIVERED"
    session["status"] = "VOIDED"
    session["void_reason"] = void_reason
    touch(session)

    if was_delivered:
        week = store.weeks.get(session["therapy_week_id"])
        if week is not None:
            _sync_week(week)
        admission = store.admissions.get(session["admission_id"])
        if admission is not None:
            propagate_admission(admission)

    return envelope(serialize(session), 200)
