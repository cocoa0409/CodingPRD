"""Course sessions: schedule / list / get / cancel."""

from flask import Blueprint, request

from db import store, base_record
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_WINDOW_INVALID,
                    ERR_CONTENT_NOT_APPROVED, ERR_ROOM_CONFLICT,
                    ERR_BLACKOUT_CONFLICT, ERR_SESSION_NOT_SCHEDULED)
from middleware import require_roles, json_body, require_fields
from response import success, paginate
from services import get_or_404, by_seq, cancel_session
from util import require_str, require_int, parse_dt, view

bp = Blueprint("sessions", __name__)

ANY = ("TrainingAdmin", "ComplianceOfficer", "RegisteredRep", "Auditor")


@bp.post("/sessions")
@require_roles("TrainingAdmin")
def create_session():
    body = json_body()
    # Existence: body FK content_id resolves (before shape per PRD 2.6 order
    # when the field is present; missing fields fall through to shape).
    content = None
    if body.get("content_id") is not None:
        content = get_or_404(store.contents, body["content_id"],
                             "TrainingContent")
    # Shape.
    require_fields(body, "content_id", "room_name", "start_at", "end_at",
                   "capacity")
    room_name = require_str(body["room_name"], "room_name")
    start_at = parse_dt(body["start_at"], "start_at")
    end_at = parse_dt(body["end_at"], "end_at")
    capacity = require_int(body["capacity"], "capacity")
    if capacity < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field 'capacity' must be >= 1")
    if not end_at > start_at:
        raise ApiError(ERR_WINDOW_INVALID, 400,
                       "Session end_at must be strictly later than start_at")
    # Target-state guard: only APPROVED content can be delivered.
    if content["content_status"] != "APPROVED":
        raise ApiError(ERR_CONTENT_NOT_APPROVED, 409,
                       "Sessions may be scheduled only for APPROVED content")
    # Temporal conflicts: room half-open overlap, then blackout closed overlap.
    for s in store.sessions.values():
        if s["room_name"] != room_name or s["session_status"] == "CANCELLED":
            continue
        if start_at < s["end_at"] and s["start_at"] < end_at:
            raise ApiError(ERR_ROOM_CONFLICT, 409,
                           "Room '%s' is already booked in that window"
                           % room_name)
    for b in store.blackouts.values():
        if start_at <= b["end_at"] and b["start_at"] <= end_at:
            raise ApiError(ERR_BLACKOUT_CONFLICT, 409,
                           "Session intersects blackout window '%s'"
                           % b["label"])
    rec = base_record()
    rec.update({
        "content_id": content["id"],
        "room_name": room_name,
        "start_at": start_at,
        "end_at": end_at,
        "capacity": capacity,
        "session_status": "SCHEDULED",
        "available_seats": capacity,
    })
    store.sessions[rec["id"]] = rec
    return success(view(rec), status=201)


@bp.get("/sessions")
@require_roles(*ANY)
def list_sessions():
    items = by_seq(store.sessions.values())
    content_id = request.args.get("content_id")
    if content_id is not None:
        items = [s for s in items if s["content_id"] == content_id]
    session_status = request.args.get("session_status")
    if session_status is not None:
        items = [s for s in items if s["session_status"] == session_status]
    items = sorted(items, key=lambda s: (s["created_at"], s["_seq"]))
    page, pagination = paginate(items)
    return success([view(s) for s in page], is_list=True, pagination=pagination)


@bp.get("/sessions/<sessionId>")
@require_roles(*ANY)
def get_session(sessionId):
    rec = get_or_404(store.sessions, sessionId, "CourseSession")
    return success(view(rec))


@bp.post("/sessions/<sessionId>/cancel")
@require_roles("TrainingAdmin")
def cancel_session_route(sessionId):
    rec = get_or_404(store.sessions, sessionId, "CourseSession")
    if rec["session_status"] != "SCHEDULED":
        raise ApiError(ERR_SESSION_NOT_SCHEDULED, 409,
                       "Only a SCHEDULED session can be cancelled")
    cancel_session(rec)
    return success(view(rec))
