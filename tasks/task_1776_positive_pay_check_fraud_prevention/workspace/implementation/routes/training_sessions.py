"""Training sessions: scheduling with per-trainer buffered conflict rule,
completion, cancellation (PRD §3.1)."""
from datetime import timedelta

from flask import Blueprint, request

import store
from auth import ALL_ROLES, authenticate, authorize, check_list_enrollment_param, check_ownership, scope_list
from errors import (
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_SESSION_NOT_COMPLETABLE,
    ERR_TRAINING_SCHEDULE_CONFLICT,
    raise_err,
)
from services import TRAINING_BUFFER_MINUTES, guard_enrollment_mutable, session_out
from util import body_json, bump, get_or_404, list_response, new_record, req_datetime, req_str, success_object

bp = Blueprint("training_sessions", __name__)


@bp.route("/treasury/training-sessions", methods=["POST"])
def create_session():
    _, role, _user = authenticate()
    authorize(role, _user, ["BankOps"])
    body = body_json()
    enrollment_id = req_str(body, "enrollment_id")
    trainer_id = req_str(body, "trainer_id")
    start = req_datetime(body, "scheduled_start")
    end = req_datetime(body, "scheduled_end")
    if end <= start:
        raise_err(ERR_INVALID_REQUEST, "scheduled_end must be after scheduled_start")
    enr = get_or_404(store.enrollments, enrollment_id, "TreasuryEnrollment")
    guard_enrollment_mutable(enr)
    # per-trainer conflict: buffered windows [start-30min, end+30min) intersect
    buf = timedelta(minutes=TRAINING_BUFFER_MINUTES)
    new_lo, new_hi = start - buf, end + buf
    for s in store.sessions.values():
        if s["trainer_id"] != trainer_id or s["status"] != "SCHEDULED":
            continue
        ex_lo, ex_hi = s["scheduled_start"] - buf, s["scheduled_end"] + buf
        if new_lo < ex_hi and ex_lo < new_hi:
            raise_err(ERR_TRAINING_SCHEDULE_CONFLICT, "Trainer has a conflicting SCHEDULED session")
    rec = new_record()
    rec.update({
        "enrollment_id": enr["id"],
        "trainer_id": trainer_id,
        "scheduled_start": start,
        "scheduled_end": end,
        "attendee_user_ids": [],
        "status": "SCHEDULED",
    })
    store.sessions[rec["id"]] = rec
    return success_object(session_out(rec), 201)


@bp.route("/treasury/training-sessions/<sid>", methods=["GET"])
def get_session(sid):
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    rec = get_or_404(store.sessions, sid, "TrainingSession")
    check_ownership(user, rec["enrollment_id"])
    return success_object(session_out(rec), 200)


@bp.route("/treasury/training-sessions", methods=["GET"])
def list_sessions():
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    enr_filter = check_list_enrollment_param(user)
    records = scope_list(store.sessions.values(), user, lambda s: s["enrollment_id"])
    if enr_filter is not None:
        records = [s for s in records if s["enrollment_id"] == enr_filter]
    for param in ("trainer_id", "status"):
        v = request.args.get(param)
        if v is not None:
            records = [s for s in records if str(s.get(param)) == v]
    return list_response(records, session_out)


@bp.route("/treasury/training-sessions/<sid>/complete", methods=["POST"])
def complete_session(sid):
    _, role, _user = authenticate()
    authorize(role, _user, ["BankOps"])
    body = body_json()
    attendees = body.get("attendee_user_ids")
    if not isinstance(attendees, list) or len(attendees) == 0 \
            or any(not isinstance(a, str) or a == "" for a in attendees):
        raise_err(ERR_INVALID_REQUEST, "attendee_user_ids must be a non-empty array of user ids")
    rec = get_or_404(store.sessions, sid, "TrainingSession")
    # body-referenced attendees: unknown id -> 404; wrong enrollment -> 400
    for attendee_id in attendees:
        u = store.users.get(attendee_id)
        if u is None:
            raise_err(ERR_NOT_FOUND, "EnrollmentUser not found: %s" % attendee_id)
        if u["enrollment_id"] != rec["enrollment_id"]:
            raise_err(ERR_INVALID_REQUEST, "attendee %s is not an EnrollmentUser of this enrollment" % attendee_id)
    enr = store.enrollments[rec["enrollment_id"]]
    guard_enrollment_mutable(enr)
    if rec["status"] != "SCHEDULED":
        raise_err(ERR_SESSION_NOT_COMPLETABLE, "Session is not SCHEDULED")
    rec["attendee_user_ids"] = list(attendees)
    rec["status"] = "COMPLETED"
    bump(rec)
    return success_object(session_out(rec), 200)


@bp.route("/treasury/training-sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    _, role, _user = authenticate()
    authorize(role, _user, ["BankOps"])
    body_json()
    rec = get_or_404(store.sessions, sid, "TrainingSession")
    enr = store.enrollments[rec["enrollment_id"]]
    guard_enrollment_mutable(enr)
    if rec["status"] != "SCHEDULED":
        raise_err(ERR_SESSION_NOT_COMPLETABLE, "Session is not SCHEDULED")
    rec["status"] = "CANCELLED"
    bump(rec)
    return success_object(session_out(rec), 200)
