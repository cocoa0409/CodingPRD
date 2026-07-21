"""The session-speaker junction: a cyclic invite / accept / withdraw loop."""

from flask import Blueprint

import calc
import cascades
import db
from auth import authorize, own_entity, own_event
from db import S, dt_of, minutes
from errors import ApiError
from response import ok, ok_list
from validate import (
    body, get_session, get_session_speaker, get_speaker, guard_state,
    pagination, paginate, qs, req_enum, req_str,
)
from routes.registrations import fk

bp = Blueprint("session_speakers", __name__)

SPEAKING_ROLES = ("HOST", "PANELIST", "MODERATOR")
SS_TERMINAL = ("DECLINED", "RELEASED")


@bp.route("/api/session-speakers", methods=["POST"])
def invite_speaker():
    authorize("Organizer")
    b = body()

    session = fk(b, "session_id", get_session)
    fk(b, "speaker_id", get_speaker)

    if session is not None:
        event = S.events.get(session.get("event_id"))
        if event is not None:
            own_event(event)

    req_str(b, "session_id")
    speaker_id = req_str(b, "speaker_id")
    speaking_role = req_enum(b, "speaking_role", SPEAKING_ROLES)

    row = db.new_row({
        "session_id": session["id"],
        "speaker_id": speaker_id,
        "speaking_role": speaking_role,
        "state": "INVITED",
        "invite_round": 1,
    })
    S.session_speakers[row["id"]] = row
    return ok(db.serialize(row), 201)


@bp.route("/api/session-speakers", methods=["GET"])
def list_session_speakers():
    authorize("Organizer", "PlatformAdmin", "SpeakerUser")
    limit, offset = pagination()
    session_id = qs("session_id")
    speaker_id = qs("speaker_id")
    state = qs("state")
    rows = [
        r for r in S.session_speakers.values()
        if (session_id is None or r.get("session_id") == session_id)
        and (speaker_id is None or r.get("speaker_id") == speaker_id)
        and (state is None or r.get("state") == state)
    ]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/session-speakers/<session_speaker_id>", methods=["GET"])
def read_session_speaker(session_speaker_id):
    authorize("Organizer", "PlatformAdmin", "SpeakerUser")
    return ok(db.serialize(get_session_speaker(session_speaker_id)))


@bp.route("/api/session-speakers/<session_speaker_id>/accept", methods=["POST"])
def accept_invitation(session_speaker_id):
    authorize("SpeakerUser")
    row = get_session_speaker(session_speaker_id)
    own_entity(row.get("speaker_id"))

    guard_state(row, ("INVITED",), SS_TERMINAL)
    session = S.sessions.get(row.get("session_id"))
    if session is None or session.get("state") not in ("DRAFT", "SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE")

    _check_speaker_buffer(row, session)

    row["state"] = "ACCEPTED"
    speaker = S.speakers.get(row.get("speaker_id"))
    if speaker is not None:
        speaker["accepted_session_count"] = int(speaker.get("accepted_session_count", 0)) + 1
        cascades.recompute_engagement(speaker)
        db.touch(speaker)
    session["accepted_speaker_count"] = int(session.get("accepted_speaker_count", 0)) + 1
    db.touch(session)
    db.touch(row)
    return ok(db.serialize(row))


def _check_speaker_buffer(row, session):
    """Buffered speaker calendar: 10 minutes of transition margin on each side."""
    buffer_delta = minutes(calc.SPEAKER_TRANSITION_BUFFER_MINUTES)
    new_start = dt_of(session, "starts_at")
    new_end = dt_of(session, "ends_at")
    for other_row in S.session_speakers.values():
        if other_row["id"] == row["id"]:
            continue
        if other_row.get("speaker_id") != row.get("speaker_id"):
            continue
        if other_row.get("state") != "ACCEPTED":
            continue
        other = S.sessions.get(other_row.get("session_id"))
        if other is None or other["id"] == session["id"]:
            continue
        other_start = dt_of(other, "starts_at")
        other_end = dt_of(other, "ends_at")
        if new_start < other_end + buffer_delta and other_start < new_end + buffer_delta:
            raise ApiError("ERR_SPEAKER_BUFFER_CONFLICT")


@bp.route("/api/session-speakers/<session_speaker_id>/decline", methods=["POST"])
def decline_invitation(session_speaker_id):
    authorize("SpeakerUser")
    row = get_session_speaker(session_speaker_id)
    own_entity(row.get("speaker_id"))
    guard_state(row, ("INVITED",), SS_TERMINAL)
    row["state"] = "DECLINED"
    db.touch(row)
    return ok(db.serialize(row))


@bp.route("/api/session-speakers/<session_speaker_id>/withdraw", methods=["POST"])
def withdraw_invitation(session_speaker_id):
    authorize("SpeakerUser")
    row = get_session_speaker(session_speaker_id)
    own_entity(row.get("speaker_id"))
    guard_state(row, ("ACCEPTED",), SS_TERMINAL)

    session = S.sessions.get(row.get("session_id"))
    if session is None or session.get("state") == "COMPLETED":
        raise ApiError("ERR_INVALID_STATE")

    row["state"] = "WITHDRAWN"
    speaker = S.speakers.get(row.get("speaker_id"))
    if speaker is not None:
        speaker["accepted_session_count"] = max(
            0, int(speaker.get("accepted_session_count", 0)) - 1
        )
        cascades.recompute_engagement(speaker)
        db.touch(speaker)
    session["accepted_speaker_count"] = max(
        0, int(session.get("accepted_speaker_count", 0)) - 1
    )
    db.touch(session)
    db.touch(row)
    return ok(db.serialize(row))


@bp.route("/api/session-speakers/<session_speaker_id>/reinvite", methods=["POST"])
def reinvite_speaker(session_speaker_id):
    authorize("Organizer")
    row = get_session_speaker(session_speaker_id)
    session = S.sessions.get(row.get("session_id"))
    if session is not None:
        event = S.events.get(session.get("event_id"))
        if event is not None:
            own_event(event)

    guard_state(row, ("WITHDRAWN",), SS_TERMINAL)
    if session is None or session.get("state") not in ("DRAFT", "SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE")

    row["state"] = "INVITED"
    row["invite_round"] = int(row.get("invite_round", 1)) + 1
    db.touch(row)
    return ok(db.serialize(row))
