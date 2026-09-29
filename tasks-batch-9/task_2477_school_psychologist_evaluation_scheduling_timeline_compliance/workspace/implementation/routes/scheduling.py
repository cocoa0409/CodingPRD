"""Interpreter sessions and the eligibility-meeting lifecycle (PRD §3.5, §3.8)."""

from flask import Blueprint, request

import calc
import lookups
import serializers
import services
import validators as v
from auth import ALL_ROLES, authorize
from envelope import paginate, pagination, respond_array, respond_object
from errors import ApiError
from store import base_record, db, iso, now, sort_key, today, touch

bp = Blueprint("scheduling", __name__)

MEETING_ACTIVE_STATUSES = ("PROPOSED", "NOTICED", "RESCHEDULE_REQUESTED")


# ---------------------------------------------------------------- interpreter sessions

@bp.post("/psych-services/interpreter-sessions")
@authorize("IntakeCoordinator", "PsychServicesSupervisor")
def book_interpreter_session():
    body = v.body()
    evaluation_id = v.req_str(body, "evaluation_id")
    language_code = v.req_str(body, "language_code")
    interpreter_name = v.req_str(body, "interpreter_name")
    start_at = v.req_dt(body, "session_start_at")
    end_at = v.req_dt(body, "session_end_at")
    if end_at <= start_at:
        raise ApiError("ERR_INVALID_REQUEST", "session_end_at must be strictly after session_start_at.")

    evaluation = lookups.evaluation(evaluation_id)

    # ladder 18 — half-open psychologist calendar with a cross-building travel buffer
    if services.calendar_conflict(evaluation, start_at, end_at):
        raise ApiError("ERR_PSYCH_CALENDAR_CONFLICT",
                       "The assigned psychologist's calendar already holds an overlapping session.")

    record = base_record()
    record.update({
        "evaluation_id": evaluation["id"],
        "language_code": language_code,
        "interpreter_name": interpreter_name,
        "session_start_at": iso(start_at),
        "session_end_at": iso(end_at),
        "status": "SCHEDULED",
        "cancellation_reason": None,
        "duration_minutes": int((end_at - start_at).total_seconds() // 60),
        "_start_at": start_at,
        "_end_at": end_at,
    })
    db.sessions[record["id"]] = record
    return respond_object(serializers.interpreter_session(record), 201)


# ---------------------------------------------------------------- eligibility meetings

@bp.post("/psych-services/eligibility-meetings")
@authorize("IntakeCoordinator", "PsychServicesSupervisor")
def create_eligibility_meeting():
    body = v.body()
    evaluation_id = v.req_str(body, "evaluation_id")
    school_id = v.req_str(body, "school_id")
    start_at = v.req_dt(body, "scheduled_start_at")
    end_at = v.req_dt(body, "scheduled_end_at")
    if end_at <= start_at:
        raise ApiError("ERR_INVALID_REQUEST",
                       "scheduled_end_at must be strictly after scheduled_start_at.")
    expected_version = v.req_int(body, "expected_evaluation_version", minimum=0)

    evaluation = lookups.evaluation(evaluation_id)
    school = lookups.school(school_id)

    # ladder 7 — optimistic concurrency control on the evaluation
    if expected_version != evaluation["version"]:
        raise ApiError("ERR_STALE_EVALUATION_VERSION",
                       "expected_evaluation_version %s does not match the current version %s."
                       % (expected_version, evaluation["version"]))

    # the meetings this creation supersedes have already released their slots
    superseded = [
        m for m in sorted(db.meetings.values(), key=sort_key)
        if m["evaluation_id"] == evaluation["id"] and m["status"] in MEETING_ACTIVE_STATUSES
    ]

    # ladder 19 — closed-interval hosting-building capacity
    if services.meeting_capacity_blocked(school, start_at, end_at, {m["id"] for m in superseded}):
        raise ApiError("ERR_SCHOOL_MEETING_CAPACITY_FULL",
                       "The hosting building has no free concurrent meeting slot for that interval.")

    for meeting in superseded:
        meeting["status"] = "SUPERSEDED"
        touch(meeting)

    record = base_record()
    record.update({
        "evaluation_id": evaluation["id"],
        "school_id": school["id"],
        "scheduled_start_at": iso(start_at),
        "scheduled_end_at": iso(end_at),
        "parent_notice_sent_at": None,
        "notice_lead_days": None,
        "reschedule_count": 0,
        "status": "PROPOSED",
        "held_at": None,
        "_start_at": start_at,
        "_end_at": end_at,
    })
    db.meetings[record["id"]] = record

    touch(evaluation)  # creating a meeting increments the parent evaluation's version

    return respond_object(serializers.eligibility_meeting(record), 201)


@bp.post("/psych-services/eligibility-meetings/<meeting_id>/notice")
@authorize("IntakeCoordinator")
def issue_meeting_notice(meeting_id):
    meeting = lookups.meeting(meeting_id)
    if meeting["status"] not in ("PROPOSED", "RESCHEDULE_REQUESTED"):
        raise ApiError("ERR_MEETING_STATE_INVALID",
                       "A notice may only be issued from PROPOSED or RESCHEDULE_REQUESTED.")

    lead_days = calc.days_between(today(), meeting["_start_at"].date())
    if lead_days < calc.PARENT_NOTICE_LEAD_DAYS:
        raise ApiError("ERR_NOTICE_LEAD_INSUFFICIENT",
                       "Statutory parent notice requires at least %d calendar days of lead."
                       % calc.PARENT_NOTICE_LEAD_DAYS)

    meeting["status"] = "NOTICED"
    meeting["parent_notice_sent_at"] = iso(now())
    meeting["notice_lead_days"] = lead_days
    touch(meeting)
    return respond_object(serializers.eligibility_meeting(meeting))


@bp.post("/psych-services/eligibility-meetings/<meeting_id>/reschedule-request")
@authorize("IntakeCoordinator")
def request_meeting_reschedule(meeting_id):
    body = v.body()
    start_at = v.req_dt(body, "scheduled_start_at")
    end_at = v.req_dt(body, "scheduled_end_at")
    if end_at <= start_at:
        raise ApiError("ERR_INVALID_REQUEST",
                       "scheduled_end_at must be strictly after scheduled_start_at.")

    meeting = lookups.meeting(meeting_id)
    if meeting["status"] != "NOTICED":
        raise ApiError("ERR_MEETING_STATE_INVALID", "Only a NOTICED meeting may be rescheduled.")

    school = db.schools.get(meeting["school_id"])
    # ladder 19 runs before ladder 23 — capacity first, then the reschedule ceiling
    if school is not None and services.meeting_capacity_blocked(
            school, start_at, end_at, {meeting["id"]}):
        raise ApiError("ERR_SCHOOL_MEETING_CAPACITY_FULL",
                       "The hosting building has no free concurrent meeting slot for that interval.")

    if meeting["reschedule_count"] >= calc.MAX_RESCHEDULES:
        raise ApiError("ERR_RESCHEDULE_LIMIT_REACHED",
                       "This meeting has already been rescheduled %d times."
                       % calc.MAX_RESCHEDULES)

    meeting["status"] = "RESCHEDULE_REQUESTED"
    meeting["scheduled_start_at"] = iso(start_at)
    meeting["scheduled_end_at"] = iso(end_at)
    meeting["_start_at"] = start_at
    meeting["_end_at"] = end_at
    meeting["reschedule_count"] += 1
    meeting["parent_notice_sent_at"] = None
    meeting["notice_lead_days"] = None
    touch(meeting)
    return respond_object(serializers.eligibility_meeting(meeting))


@bp.post("/psych-services/eligibility-meetings/<meeting_id>/hold")
@authorize("PsychServicesSupervisor")
def hold_meeting(meeting_id):
    meeting = lookups.meeting(meeting_id)
    if meeting["status"] != "NOTICED":
        raise ApiError("ERR_MEETING_STATE_INVALID", "Only a NOTICED meeting may be recorded as held.")

    evaluation = db.evaluations.get(meeting["evaluation_id"])

    # ladder 10 — the cross-entity report gate
    if evaluation is None or evaluation["assessment_status"] != "REPORT_FINAL":
        raise ApiError("ERR_REPORT_NOT_FINAL",
                       "The evaluation report must be REPORT_FINAL before a determination is recorded.")

    # ladder 22 — the meeting must actually be due
    if now() < meeting["_start_at"]:
        raise ApiError("ERR_MEETING_NOT_DUE",
                       "The meeting cannot be recorded as held before its scheduled start.")

    meeting["status"] = "HELD"
    meeting["held_at"] = iso(now())
    touch(meeting)

    if evaluation["compliance_status"] not in calc.CLOSED_COMPLIANCE_STATUSES and \
            services.days_remaining_of(evaluation) >= 0:
        services.freeze_clock(evaluation)
        evaluation["compliance_status"] = "COMPLIANT_CLOSED"
        touch(evaluation)
        services.recompute_psychologist(evaluation["psychologist_id"])

    referral = db.referrals.get(evaluation["referral_id"])
    if referral is not None and referral["status"] in ("CONSENTED", "CONSENT_WAIVED"):
        referral["status"] = "COMPLETED"
        touch(referral)

    return respond_object(serializers.eligibility_meeting(meeting))


@bp.get("/psych-services/eligibility-meetings/<meeting_id>")
@authorize(*ALL_ROLES)
def get_meeting(meeting_id):
    record = lookups.meeting(meeting_id)
    return respond_object(serializers.eligibility_meeting(record))


@bp.get("/psych-services/eligibility-meetings")
@authorize(*ALL_ROLES)
def list_meetings():
    limit, offset = pagination(request.args)
    rows = list(db.meetings.values())
    for field in ("evaluation_id", "school_id", "status"):
        wanted = request.args.get(field)
        if wanted:
            rows = [r for r in rows if r[field] == wanted]
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return respond_array([serializers.eligibility_meeting(r) for r in page], limit, offset, total)
