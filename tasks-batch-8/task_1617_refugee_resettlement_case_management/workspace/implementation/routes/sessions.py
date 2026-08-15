"""OrientationSession endpoints (30-minute buffer, one delivery per topic)."""

from datetime import timedelta

from flask import Blueprint

from db import store, clock_date, new_id, stamp_new, touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
    ERR_INVALID_STATE,
    ERR_SESSION_SCHEDULE_CONFLICT,
    ERR_TOPIC_ALREADY_DELIVERED,
    ERR_TOPIC_ALREADY_SCHEDULED,
    ERR_CASE_TRANSFER_PENDING,
)
from helpers import body_dict, req_string, req_enum, req_datetime
from middleware import authenticate, authorize, CASE_MANAGER
from response import success_object, success_list
from serializers import ser_session
from services import ALL_TOPICS, sessions_of_case, sorted_records
from routes.cases import get_case_or_404

bp = Blueprint("sessions", __name__)

BUFFER = timedelta(minutes=30)
TOPIC_SET = set(ALL_TOPICS)


def get_session_or_404(session_id):
    s = store.orientation_sessions.get(session_id)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Orientation session not found.")
    return s


@bp.post("/orientation-sessions")
def create_session():
    _uid, role = authenticate()
    authorize(role, {CASE_MANAGER})
    d = body_dict()
    # Priority 3: body FK existence
    case_id = req_string(d, "case_id")
    case = store.cases.get(case_id)
    if case is None:
        raise ApiError(ERR_NOT_FOUND, 404, "case_id does not identify an existing case.")
    # Priority 4: schema — topic enum and end strictly after start
    topic = req_enum(d, "topic", TOPIC_SET)
    start_at = req_datetime(d, "start_at")
    end_at = req_datetime(d, "end_at")
    if not end_at > start_at:
        raise ApiError(ERR_VALIDATION, 400, "end_at must be strictly after start_at.")
    # Priority 6: state — the case must be ARRIVED
    if case["status"] != "ARRIVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Case must be ARRIVED to schedule a session.")
    existing = sessions_of_case(case["id"])
    # Priority 8: 30-minute buffer against every SCHEDULED/COMPLETED session
    # of the same case. A gap of exactly 30 minutes is allowed.
    for other in existing:
        if other["status"] in ("SCHEDULED", "COMPLETED"):
            if start_at < other["end_at"] + BUFFER and other["start_at"] < end_at + BUFFER:
                raise ApiError(
                    ERR_SESSION_SCHEDULE_CONFLICT,
                    409,
                    "Session violates the 30-minute buffer against another session.",
                )
    # Priority 9: topic not already delivered, not already scheduled,
    # then the transfer freeze.
    if any(s["topic"] == topic and s["status"] == "COMPLETED" for s in existing):
        raise ApiError(ERR_TOPIC_ALREADY_DELIVERED, 409, "Topic already delivered for this case.")
    if any(s["topic"] == topic and s["status"] == "SCHEDULED" for s in existing):
        raise ApiError(ERR_TOPIC_ALREADY_SCHEDULED, 409, "A session for this topic is already scheduled.")
    if case["open_transfer_id"] is not None:
        raise ApiError(ERR_CASE_TRANSFER_PENDING, 409, "Case has an open transfer.")
    session = {
        "id": new_id(),
        "case_id": case["id"],
        "topic": topic,
        "start_at": start_at,
        "end_at": end_at,
        "status": "SCHEDULED",
        "completed_on": None,
    }
    stamp_new(session)
    store.orientation_sessions[session["id"]] = session
    return success_object(ser_session(session), 201)


@bp.get("/cases/<case_id>/orientation-sessions")
def list_sessions_of_case(case_id):
    authenticate()
    case = get_case_or_404(case_id)
    return success_list(sorted_records(sessions_of_case(case["id"])), ser_session)


@bp.post("/orientation-sessions/<session_id>/complete")
def complete_session(session_id):
    _uid, role = authenticate()
    authorize(role, {CASE_MANAGER})
    session = get_session_or_404(session_id)
    # Priority 6: state
    if session["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SCHEDULED session can be completed.")
    # Priority 9: transfer freeze
    case = store.cases[session["case_id"]]
    if case["open_transfer_id"] is not None:
        raise ApiError(ERR_CASE_TRANSFER_PENDING, 409, "Case has an open transfer.")
    session["status"] = "COMPLETED"
    session["completed_on"] = clock_date()
    touch(session)
    # If topics_completed now covers all six topics, auto-fulfill the
    # CULTURAL_ORIENTATION benchmark (system fulfillment, no evidence note).
    completed_topics = {
        s["topic"] for s in sessions_of_case(case["id"]) if s["status"] == "COMPLETED"
    }
    if completed_topics >= TOPIC_SET:
        for b in store.benchmarks.values():
            if (
                b["case_id"] == case["id"]
                and b["service_type"] == "CULTURAL_ORIENTATION"
                and b["status"] == "PENDING"
            ):
                b["status"] = "MET"
                b["fulfilled_on"] = session["completed_on"]
                b["evidence_note_id"] = None
                b["on_time"] = b["fulfilled_on"] <= b["due_date"]
                touch(b)
    return success_object(ser_session(session), 200)
