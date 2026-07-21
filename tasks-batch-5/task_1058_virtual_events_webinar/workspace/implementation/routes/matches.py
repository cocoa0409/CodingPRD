"""Networking and matchmaking: closed meeting-window geometry (PRD 3.9)."""

from flask import Blueprint

import calc
import db
from auth import authorize, own_entity, own_event
from db import S, dt_of, minutes
from errors import ApiError
from response import ok, ok_list
from validate import (
    body, get_event, get_match_request, get_registration, guard_state,
    pagination, paginate, qs, req_dt, req_str,
)
from routes.registrations import fk

bp = Blueprint("matches", __name__)

MATCH_TERMINAL = ("DECLINED", "EXPIRED", "CANCELLED")


@bp.route("/api/match-requests", methods=["POST"])
def create_match_request():
    authorize("Attendee")
    b = body()

    # 4. body foreign keys, in declared field order
    event = fk(b, "event_id", get_event)
    requester = fk(b, "requester_registration_id", get_registration)
    target = fk(b, "target_registration_id", get_registration)

    # 5. ownership - the requester acts as their own registration
    if requester is not None:
        own_entity(requester["id"])

    # 6. body shape
    req_str(b, "event_id")
    req_str(b, "requester_registration_id")
    req_str(b, "target_registration_id")
    window_start = req_dt(b, "window_start")
    window_end = req_dt(b, "window_end")

    # 7. interval well-formedness
    if window_end <= window_start:
        raise ApiError("ERR_TIME_RANGE_INVALID")

    # 13. referential consistency
    if (
        requester.get("event_id") != event["id"]
        or target.get("event_id") != event["id"]
    ):
        raise ApiError("ERR_REGISTRATION_EVENT_MISMATCH")
    if requester["id"] == target["id"]:
        raise ApiError("ERR_SELF_MATCH_NOT_ALLOWED")

    expires_at = window_start - minutes(calc.MATCH_EXPIRY_LEAD_MINUTES)

    row = db.new_row({
        "event_id": event["id"],
        "requester_registration_id": requester["id"],
        "target_registration_id": target["id"],
        "window_start": db.fmt_dt(window_start),
        "window_end": db.fmt_dt(window_end),
        "expires_at": db.fmt_dt(expires_at),
        "state": "PENDING",
    })
    S.match_requests[row["id"]] = row
    return ok(db.serialize(row), 201)


@bp.route("/api/match-requests", methods=["GET"])
def list_match_requests():
    authorize("Attendee", "Organizer", "PlatformAdmin")
    limit, offset = pagination()
    event_id = qs("event_id")
    requester_registration_id = qs("requester_registration_id")
    target_registration_id = qs("target_registration_id")
    state = qs("state")
    rows = [
        r for r in S.match_requests.values()
        if (event_id is None or r.get("event_id") == event_id)
        and (requester_registration_id is None
             or r.get("requester_registration_id") == requester_registration_id)
        and (target_registration_id is None
             or r.get("target_registration_id") == target_registration_id)
        and (state is None or r.get("state") == state)
    ]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/match-requests/<match_request_id>", methods=["GET"])
def read_match_request(match_request_id):
    authorize("Attendee", "Organizer", "PlatformAdmin")
    return ok(db.serialize(get_match_request(match_request_id)))


@bp.route("/api/match-requests/<match_request_id>/accept", methods=["POST"])
def accept_match_request(match_request_id):
    authorize("Attendee")
    row = get_match_request(match_request_id)
    own_entity(row.get("target_registration_id"))

    guard_state(row, ("PENDING",), MATCH_TERMINAL)

    # 14. temporal geometry: window conflict, then expiry
    _check_meeting_conflicts(row)
    expires_at = dt_of(row, "expires_at")
    if expires_at is not None and S.now() >= expires_at:
        raise ApiError("ERR_MATCH_REQUEST_EXPIRED")

    row["state"] = "ACCEPTED"
    for reg_id in (row.get("requester_registration_id"), row.get("target_registration_id")):
        reg = S.registrations.get(reg_id)
        if reg is not None:
            reg["accepted_meeting_count"] = int(reg.get("accepted_meeting_count", 0)) + 1
            db.touch(reg)
    db.touch(row)
    return ok(db.serialize(row))


def _check_meeting_conflicts(row):
    """Closed intervals: meetings that merely touch at an endpoint DO conflict."""
    new_start = dt_of(row, "window_start")
    new_end = dt_of(row, "window_end")
    participants = {
        row.get("requester_registration_id"),
        row.get("target_registration_id"),
    }
    for other in S.match_requests.values():
        if other["id"] == row["id"]:
            continue
        if other.get("state") != "ACCEPTED":
            continue
        other_participants = {
            other.get("requester_registration_id"),
            other.get("target_registration_id"),
        }
        if not (participants & other_participants):
            continue
        other_start = dt_of(other, "window_start")
        other_end = dt_of(other, "window_end")
        if new_start <= other_end and other_start <= new_end:
            raise ApiError("ERR_MEETING_WINDOW_CONFLICT")


@bp.route("/api/match-requests/<match_request_id>/decline", methods=["POST"])
def decline_match_request(match_request_id):
    authorize("Attendee")
    row = get_match_request(match_request_id)
    own_entity(row.get("target_registration_id"))
    guard_state(row, ("PENDING",), MATCH_TERMINAL)
    row["state"] = "DECLINED"
    db.touch(row)
    return ok(db.serialize(row))


@bp.route("/api/events/<event_id>/matchmaking/sweep", methods=["POST"])
def matchmaking_sweep(event_id):
    authorize("Organizer")
    event = get_event(event_id)
    own_event(event)

    now = S.now()
    expired_count = 0
    for row in db.sort_rows(list(S.match_requests.values())):
        if row.get("event_id") != event["id"] or row.get("state") != "PENDING":
            continue
        expires_at = dt_of(row, "expires_at")
        if expires_at is not None and now >= expires_at:
            row["state"] = "EXPIRED"
            db.touch(row)
            expired_count += 1

    return ok({"expired_count": expired_count})
