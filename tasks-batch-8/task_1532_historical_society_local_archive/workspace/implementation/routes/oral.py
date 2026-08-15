"""OralHistoryRecording routes (PRD §3.9) — parallel workflow/release
dimensions and the 30-minute studio turnaround buffer."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_RECORDING_ROOM_CONFLICT, ERR_NARRATOR_MISMATCH,
    ERR_RELEASE_FORM_MISSING, ERR_ORAL_HISTORY_EMBARGOED,
)
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from util import (
    get_json_body, as_str, as_enum, parse_iso8601, parse_iso8601_opt,
    paginate, public_view,
)

bp = Blueprint("oral", __name__)

RECORDING_ROOMS = {"STUDIO_A", "STUDIO_B"}
TURNAROUND = timedelta(minutes=30)
CANCELLABLE_STATES = ("SCHEDULED", "RECORDED", "TRANSCRIBED", "IN_REVIEW")


def serialize_recording(r: dict) -> dict:
    return public_view(r)


def _get_recording(rid: str) -> dict:
    r = db.oral_histories.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, f"OralHistoryRecording not found: {rid}")
    return r


@bp.route("/oral-histories", methods=["POST"])
@require_roles("Archivist")
def create_oral_history(_user_id: str, _role: str):
    body = get_json_body()
    collection_id = as_str(body, "collection_id", required=True)
    narrator_name = as_str(body, "narrator_name", required=True)
    interviewer_name = as_str(body, "interviewer_name", required=True)
    recording_room_id = as_enum(body, "recording_room_id", RECORDING_ROOMS, required=True)
    session_start_raw = as_str(body, "session_start", required=True)
    session_end_raw = as_str(body, "session_end", required=True)
    start_dt = parse_iso8601(session_start_raw, "session_start")
    end_dt = parse_iso8601(session_end_raw, "session_end")
    if start_dt >= end_dt:
        raise_err(ERR_INVALID_REQUEST, "session_start must be strictly before session_end")

    if collection_id not in db.collections:
        raise_err(ERR_NOT_FOUND, f"Collection not found: {collection_id}")

    # single-resource-per-room with a 30-minute turnaround buffer; only
    # non-CANCELLED sessions participate. A gap of exactly 30 minutes is allowed.
    for r in db.oral_histories.values():
        if r["recording_room_id"] != recording_room_id or r["status"] == "CANCELLED":
            continue
        if not (end_dt + TURNAROUND <= r["_session_start_dt"]
                or r["_session_end_dt"] + TURNAROUND <= start_dt):
            raise_err(ERR_RECORDING_ROOM_CONFLICT, "Session conflicts with an existing studio booking")

    rec = {
        **db.make_common_fields(),
        "collection_id": collection_id,
        "narrator_name": narrator_name,
        "interviewer_name": interviewer_name,
        "recording_room_id": recording_room_id,
        "session_start": session_start_raw,
        "session_end": session_end_raw,
        "status": "SCHEDULED",
        "release_status": "PENDING",
        "release_signed_at": None,
        "embargo_until": None,
        "_session_start_dt": start_dt,
        "_session_end_dt": end_dt,
        "_embargo_dt": None,
    }
    db.oral_histories[rec["id"]] = rec
    return success_object(serialize_recording(rec), 201)


@bp.route("/oral-histories", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_oral_histories(_user_id: str, _role: str):
    collection_id = request.args.get("collection_id")
    status = request.args.get("status")
    rows = list(db.oral_histories.values())
    if collection_id is not None:
        rows = [r for r in rows if r["collection_id"] == collection_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return success_list([serialize_recording(r) for r in page], limit, offset, total)


@bp.route("/oral-histories/<rid>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_oral_history(rid: str, _user_id: str, _role: str):
    return success_object(serialize_recording(_get_recording(rid)))


def _transition(rid: str, from_state: str, to_state: str, action: str):
    rec = _get_recording(rid)
    if rec["status"] != from_state:
        raise_err(ERR_INVALID_STATE, f"Only a {from_state} recording may {action}")
    rec["status"] = to_state
    db.touch(rec)
    return success_object(serialize_recording(rec))


@bp.route("/oral-histories/<rid>/mark-recorded", methods=["POST"])
@require_roles("Archivist")
def mark_recorded(rid: str, _user_id: str, _role: str):
    return _transition(rid, "SCHEDULED", "RECORDED", "be marked recorded")


@bp.route("/oral-histories/<rid>/submit-transcript", methods=["POST"])
@require_roles("Archivist")
def submit_transcript(rid: str, _user_id: str, _role: str):
    return _transition(rid, "RECORDED", "TRANSCRIBED", "submit a transcript")


@bp.route("/oral-histories/<rid>/send-to-review", methods=["POST"])
@require_roles("Archivist")
def send_to_review(rid: str, _user_id: str, _role: str):
    return _transition(rid, "TRANSCRIBED", "IN_REVIEW", "be sent to review")


@bp.route("/oral-histories/<rid>/return-to-transcription", methods=["POST"])
@require_roles("Archivist")
def return_to_transcription(rid: str, _user_id: str, _role: str):
    return _transition(rid, "IN_REVIEW", "TRANSCRIBED", "be returned to transcription")


@bp.route("/oral-histories/<rid>/release-forms/sign", methods=["POST"])
@require_roles("Archivist")
def sign_release(rid: str, _user_id: str, _role: str):
    body = get_json_body()
    signed_by = as_str(body, "signed_by_narrator_name", required=True)
    embargo_raw = body.get("embargo_until")
    embargo_dt = parse_iso8601_opt(body, "embargo_until")

    rec = _get_recording(rid)
    if rec["release_status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "Only a PENDING release may be signed")
    if signed_by != rec["narrator_name"]:
        raise_err(ERR_NARRATOR_MISMATCH, "signed_by_narrator_name must equal the narrator_name exactly")

    rec["release_status"] = "SIGNED"
    rec["release_signed_at"] = db.now_iso()
    rec["embargo_until"] = embargo_raw
    rec["_embargo_dt"] = embargo_dt
    db.touch(rec)
    return success_object(serialize_recording(rec))


@bp.route("/oral-histories/<rid>/release-forms/decline", methods=["POST"])
@require_roles("Archivist")
def decline_release(rid: str, _user_id: str, _role: str):
    rec = _get_recording(rid)
    if rec["release_status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "Only a PENDING release may be declined")
    rec["release_status"] = "DECLINED"
    db.touch(rec)
    return success_object(serialize_recording(rec))


@bp.route("/oral-histories/<rid>/publish-release", methods=["POST"])
@require_roles("Archivist")
def publish_release(rid: str, _user_id: str, _role: str):
    rec = _get_recording(rid)
    if rec["status"] != "IN_REVIEW":
        raise_err(ERR_INVALID_STATE, "Only an IN_REVIEW recording may be published")
    if rec["release_status"] != "SIGNED":
        raise_err(ERR_RELEASE_FORM_MISSING, "Publication requires a SIGNED release form")
    if rec.get("_embargo_dt") is not None and rec["_embargo_dt"] > db.get_now():
        raise_err(ERR_ORAL_HISTORY_EMBARGOED, "The release embargo has not lapsed")
    rec["status"] = "RELEASED"
    db.touch(rec)
    return success_object(serialize_recording(rec))


@bp.route("/oral-histories/<rid>/cancel", methods=["POST"])
@require_roles("Archivist")
def cancel(rid: str, _user_id: str, _role: str):
    rec = _get_recording(rid)
    if rec["status"] not in CANCELLABLE_STATES:
        raise_err(ERR_INVALID_STATE, "Only a non-terminal recording may be cancelled")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return success_object(serialize_recording(rec))
