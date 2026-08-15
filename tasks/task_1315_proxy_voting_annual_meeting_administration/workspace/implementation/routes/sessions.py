"""MeetingPlatformSession endpoints (PRD §3.5).

Half-open [start_at, end_at) windows: overlapping sessions of the same meeting
are rejected; windows that merely touch (one ends exactly when the next
begins) are permitted. Sessions are immutable once booked.
"""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_MEETING_MODE_INCOMPATIBLE,
    ERR_MEETING_NOT_FOUND,
    ERR_SESSION_NOT_FOUND,
    ERR_SESSION_OVERLAP,
)
from middleware import require_roles
from response import success_object, success_list
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_enum,
    require_field,
    sort_by_created_at,
)

bp = Blueprint("sessions", __name__)

SESSION_TYPES = {"REHEARSAL", "LIVE"}


def get_session_or_404(session_id: str) -> dict:
    session = db.sessions.get(session_id)
    if session is None:
        raise_err(ERR_SESSION_NOT_FOUND, "MeetingPlatformSession id does not exist")
    return session


@bp.route("/proxy/platform-sessions", methods=["POST"])
@require_roles("ProxyAdministrator")
def create_session(_user_id: str, _role: str):
    body = get_json_body()
    meeting_id = require_field(body, "meeting_id")
    meeting = db.meetings.get(meeting_id)
    if meeting is None:
        raise_err(ERR_MEETING_NOT_FOUND, "Meeting id does not exist")

    # Temporal (precedence 6): the window must be well-formed.
    start_at = require_field(body, "start_at")
    end_at = require_field(body, "end_at")
    start_dt = parse_iso8601(start_at, "start_at")
    end_dt = parse_iso8601(end_at, "end_at")
    if not end_dt > start_dt:
        raise_err(ERR_INVALID_REQUEST, "end_at must be strictly after start_at")

    # Domain (precedence 8): mode compatibility, then overlap.
    if meeting["meeting_mode"] == "IN_PERSON":
        raise_err(
            ERR_MEETING_MODE_INCOMPATIBLE,
            "Platform sessions require a VIRTUAL or HYBRID meeting",
        )
    for existing in db.sessions.values():
        if existing["meeting_id"] != meeting_id:
            continue
        ex_start = parse_iso8601(existing["start_at"], "start_at")
        ex_end = parse_iso8601(existing["end_at"], "end_at")
        # Half-open windows: adjacency (touching endpoints) is allowed.
        if start_dt < ex_end and ex_start < end_dt:
            raise_err(
                ERR_SESSION_OVERLAP,
                "Session window overlaps an existing session of the meeting",
            )

    # Shape (precedence 10).
    session_type = require_enum(body, "session_type", SESSION_TYPES)

    session = {
        "meeting_id": meeting_id,
        "session_type": session_type,
        "start_at": start_at,
        "end_at": end_at,
        "status": "SCHEDULED",
    }
    db.stamp_new(session)
    db.sessions[session["id"]] = session
    return success_object(serialize(session), 201)


@bp.route("/proxy/platform-sessions", methods=["GET"])
@require_roles("ProxyAdministrator", "TransferAgent", "InspectorOfElection")
def list_sessions(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.sessions.values()))
    items = apply_filters(items, ["meeting_id", "session_type"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/proxy/platform-sessions/<session_id>", methods=["GET"])
@require_roles("ProxyAdministrator", "TransferAgent", "InspectorOfElection")
def get_session(session_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_session_or_404(session_id)))
