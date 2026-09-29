"""Spokesperson designation and media interviews (PRD 3.7).

Endpoints in this module (5):
  POST   /crisis/media-interviews
  GET    /crisis/media-interviews/{interview_id}
  GET    /crisis/media-interviews
  POST   /crisis/media-interviews/{interview_id}/confirm
  POST   /crisis/media-interviews/{interview_id}/cancel
"""

from datetime import timedelta

from flask import Blueprint

import logic as L
from core import (
    ALL_ROLES,
    Field,
    authenticate,
    enum_filter,
    fail,
    floor_minutes,
    new_record,
    ok,
    ok_list,
    pagination,
    paged,
    store,
    str_filter,
    touch,
    validate_body,
)

bp = Blueprint("interview", __name__)

INTERVIEW_STATES = ("SCHEDULED", "CONFIRMED", "CANCELLED")
BUFFER = timedelta(minutes=L.INTERVIEW_BUFFER_MINUTES)


def interview_incident(interview):
    incident = store.incidents.get(interview["incident_id"])
    if incident is None:
        fail("ERR_INCIDENT_NOT_FOUND", "The interview's incident no longer resolves.")
    return incident


@bp.post("/crisis/media-interviews")
def create_interview():
    authenticate(("CommsLead",))
    body = validate_body(
        [
            Field("incident_id", "id", required=True),
            Field("spokesperson_member_id", "id", required=True),
            Field("channel_id", "id", required=True),
            Field("outlet_name", "string", required=True, max_len=160),
            Field("scheduled_start_at", "datetime", required=True),
            Field("scheduled_end_at", "datetime", required=True),
            Field("anticipated_question_count", "int", default=0, min=0),
        ]
    )
    # 4. the interval must satisfy end strictly after start.
    if body["scheduled_end_at"] <= body["scheduled_start_at"]:
        fail("ERR_INVALID_REQUEST", "scheduled_end_at must be strictly after scheduled_start_at.")
    # 6. foreign keys in the PRD 2.5 order.
    incident = L.get_incident(body["incident_id"])
    channel = L.get_channel(body["channel_id"])
    member = L.get_member(body["spokesperson_member_id"])
    # 11. and 12.
    L.require_activated(incident)
    L.require_not_frozen(incident)
    # 22. buffered calendar check across every live booking for this speaker.
    start = body["scheduled_start_at"]
    end = body["scheduled_end_at"]
    for other in store.interviews.values():
        if other["spokesperson_member_id"] != member["id"]:
            continue
        if other["state"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        if start < other["scheduled_end_at"] + BUFFER and end + BUFFER > other["scheduled_start_at"]:
            fail(
                "ERR_SPOKESPERSON_DOUBLE_BOOKED",
                "The spokesperson already holds a clashing booking within the 30-minute buffer.",
            )
    duration = floor_minutes(start, end)
    if duration < 1:
        duration = 1
    interview = new_record(
        {
            "incident_id": incident["id"],
            "spokesperson_member_id": member["id"],
            "channel_id": channel["id"],
            "outlet_name": body["outlet_name"],
            "scheduled_start_at": start,
            "scheduled_end_at": end,
            "duration_minutes": duration,
            "anticipated_question_count": body["anticipated_question_count"],
            "high_risk_answers_approved_count": 0,
            "state": "SCHEDULED",
            "confirmed_at": None,
            "cancel_reason": None,
        }
    )
    store.interviews[interview["id"]] = interview
    L.refresh(incident)
    return ok(interview, 201)


@bp.get("/crisis/media-interviews/<interview_id>")
def read_interview(interview_id):
    authenticate(ALL_ROLES)
    return ok(L.get_interview(interview_id))


@bp.get("/crisis/media-interviews")
def list_interviews():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    incident_id = str_filter("incident_id")
    spokesperson = str_filter("spokesperson_member_id")
    channel_id = str_filter("channel_id")
    state = enum_filter("state", INTERVIEW_STATES)
    rows = list(store.interviews.values())
    if incident_id is not None:
        rows = [r for r in rows if r["incident_id"] == incident_id]
    if spokesperson is not None:
        rows = [r for r in rows if r["spokesperson_member_id"] == spokesperson]
    if channel_id is not None:
        rows = [r for r in rows if r["channel_id"] == channel_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    window, total = paged(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/crisis/media-interviews/<interview_id>/confirm")
def confirm_interview(interview_id):
    authenticate(("CommsLead",))
    body = validate_body(
        [Field("high_risk_answers_approved_count", "int", required=True, min=0)]
    )
    interview = L.get_interview(interview_id)
    # 10. from-state.
    if interview["state"] != "SCHEDULED":
        fail("ERR_INTERVIEW_STATE_INVALID", "Only a SCHEDULED interview may be confirmed.")
    incident = interview_incident(interview)
    # 12. confirmation is the one operation that demands a fully OPEN posture.
    L.require_open_posture(incident)
    high_risk = body["high_risk_answers_approved_count"]
    member = store.members.get(interview["spokesperson_member_id"])
    if member is None:
        fail("ERR_TEAM_MEMBER_NOT_FOUND", "The spokesperson no longer resolves.")
    now = store.now()
    # 27. media training must be current and not lapse at or before this instant.
    if (
        member["media_training_status"] != "CURRENT"
        or member["media_training_expires_at"] is None
        or not member["media_training_expires_at"] > now
    ):
        fail("ERR_TRAINING_NOT_CURRENT", "The spokesperson's media training is not current.")
    # 28. anticipated-question pack completeness.
    if (
        interview["anticipated_question_count"] < L.QUESTION_PACK_MIN_QUESTIONS
        or high_risk < L.QUESTION_PACK_MIN_HIGH_RISK
    ):
        fail("ERR_QUESTION_PACK_INCOMPLETE", "The anticipated-question pack is incomplete.")
    interview["high_risk_answers_approved_count"] = high_risk
    interview["state"] = "CONFIRMED"
    interview["confirmed_at"] = now
    touch(interview)
    L.bump_member(member, L.recompute_scheduled_interview_minutes)
    L.refresh(incident)
    touch(incident)
    return ok(interview)


@bp.post("/crisis/media-interviews/<interview_id>/cancel")
def cancel_interview(interview_id):
    authenticate(("CommsLead", "Spokesperson"))
    body = validate_body([Field("cancel_reason", "string", required=True)])
    interview = L.get_interview(interview_id)
    if interview["state"] not in ("SCHEDULED", "CONFIRMED"):
        fail("ERR_INTERVIEW_STATE_INVALID", "A CANCELLED interview cannot be cancelled again.")
    incident = interview_incident(interview)
    L.require_not_frozen(incident)
    from_state = interview["state"]
    interview["state"] = "CANCELLED"
    interview["cancel_reason"] = body["cancel_reason"]
    touch(interview)
    if from_state == "CONFIRMED":
        member = store.members.get(interview["spokesperson_member_id"])
        if member is not None:
            L.bump_member(member, L.recompute_scheduled_interview_minutes)
        L.refresh(incident)
        touch(incident)
    else:
        # SCHEDULED bookings never contributed to the conserved load ledger.
        L.refresh(incident)
    return ok(interview)
