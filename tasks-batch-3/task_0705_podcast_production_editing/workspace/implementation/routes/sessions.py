"""Session endpoints — recording & booking windows (PRD §3.3)."""
from datetime import timedelta

from flask import Blueprint, request

import errors
import middleware as mw
from clock import clock
from constants import CAPTURE_MODES
from db import db
from response import array_response, object_response
from routes.common import assert_session_engineer, get_or_404
from serialize import serialize, serialize_list
from services import calc, show_state
from timeutil import parse_iso8601

bp = Blueprint("sessions", __name__)


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: true overlap, touching endpoints allowed."""
    return a_start < b_end and b_start < a_end


@bp.post("/sessions")
def create_session():
    auth = mw.authenticate()
    mw.require_role(auth, {"ProducerEng"})
    body = mw.get_json_body()
    # existence left-to-right: episode then engineer
    episode_id = mw.require_string(body, "episode_id")
    episode = get_or_404(db.episodes, episode_id)
    engineer_id = mw.require_string(body, "engineer_id")
    engineer = get_or_404(db.engineers, engineer_id)
    # ownership: a ProducerEng books on their own engineer identity
    assert_session_engineer(auth, {"engineer_id": engineer_id})
    capture_mode = mw.require_enum(body, "capture_mode", CAPTURE_MODES)
    start_raw = mw.require_string(body, "scheduled_start_utc")
    end_raw = mw.require_string(body, "scheduled_end_utc")
    try:
        start = parse_iso8601(start_raw)
        end = parse_iso8601(end_raw)
    except ValueError:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid datetime")
    # window well-formedness (priority 26)
    if not (end > start):
        raise errors.err(errors.ERR_INVALID_WINDOW, "end must be strictly after start")
    # posture gate (priority 13)
    show = db.shows.get(episode["show_id"])
    if show is None or show["production_posture"] != "ACTIVE":
        raise errors.err(errors.ERR_SHOW_NOT_ACTIVE, "Show is not ACTIVE")
    # temporal capacity (priority 24 STUDIO / 25 REMOTE)
    eng_sessions = [
        s for s in db.sessions.all()
        if s["engineer_id"] == engineer_id and s["status"] != "CANCELLED"
    ]
    if capture_mode == "STUDIO":
        for s in eng_sessions:
            if s["capture_mode"] != "STUDIO":
                continue
            if _overlaps(start, end, s["scheduled_start_utc"], s["scheduled_end_utc"]):
                raise errors.err(errors.ERR_SESSION_OVERLAP, "STUDIO session window overlaps")
    else:  # REMOTE
        buffer_delta = timedelta(minutes=engineer["remote_buffer_minutes"])
        for s in eng_sessions:
            if s["capture_mode"] != "REMOTE":
                continue
            # separation >= buffer in either ordering; gap exactly equal allowed.
            earlier_end = s["scheduled_end_utc"]
            later_start = start
            ok_after = later_start >= earlier_end + buffer_delta
            ok_before = s["scheduled_start_utc"] >= end + buffer_delta
            if not (ok_after or ok_before):
                raise errors.err(errors.ERR_REMOTE_BUFFER_VIOLATION,
                                 "REMOTE session too close to another")
    # engineer active (priority 29)
    if not engineer["active"]:
        raise errors.err(errors.ERR_ENGINEER_INACTIVE, "Engineer is inactive")
    rec = db.sessions.create({
        "episode_id": episode_id,
        "engineer_id": engineer_id,
        "capture_mode": capture_mode,
        "scheduled_start_utc": start,
        "scheduled_end_utc": end,
        "status": "BOOKED",
        "completed_at": None,
    })
    return object_response(serialize(rec), status=201)


@bp.get("/sessions")
def list_sessions():
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ProducerEng"})
    limit, offset = mw.parse_pagination()
    records = db.sessions.all()
    episode_id = request.args.get("episode_id")
    engineer_id = request.args.get("engineer_id")
    status = request.args.get("status")
    if episode_id is not None:
        records = [r for r in records if r["episode_id"] == episode_id]
    if engineer_id is not None:
        records = [r for r in records if r["engineer_id"] == engineer_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, meta = mw.paginate(records, limit, offset)
    return array_response(serialize_list(page), meta)


@bp.get("/sessions/<rid>")
def get_session(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ProducerEng"})
    rec = get_or_404(db.sessions, rid)
    return object_response(serialize(rec))


@bp.post("/sessions/<rid>/start")
def start_session(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"ProducerEng"})
    rec = get_or_404(db.sessions, rid)
    assert_session_engineer(auth, rec)
    if rec["status"] != "BOOKED":
        raise errors.err(errors.ERR_INVALID_STATE, "Session is not BOOKED")
    episode = db.episodes.get(rec["episode_id"])
    if episode is None or episode["status"] not in {"INTAKE", "RECORDING"}:
        raise errors.err(errors.ERR_INVALID_STATE, "Episode not in INTAKE/RECORDING")
    rec["status"] = "LIVE"
    db.sessions.touch(rec)
    if episode["status"] == "INTAKE":
        episode["status"] = "RECORDING"
        db.episodes.touch(episode)
    return object_response(serialize(rec))


@bp.post("/sessions/<rid>/complete")
def complete_session(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"ProducerEng"})
    rec = get_or_404(db.sessions, rid)
    assert_session_engineer(auth, rec)
    if rec["status"] != "LIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Session is not LIVE")
    rec["completed_at"] = clock.now()
    rec["status"] = "COMPLETED"
    db.sessions.touch(rec)
    # bubble episode RECORDING -> EDITING; provisional turnaround (PRD §3.3/§3.6)
    episode = db.episodes.get(rec["episode_id"])
    if episode is not None and episode["status"] == "RECORDING":
        episode["status"] = "EDITING"
        episode["recording_ended_at"] = rec["completed_at"]
        contract = db.contracts.get(episode["contract_id"])
        if contract is not None:
            episode["turnaround_due_utc"] = calc.turnaround_due(
                episode["recording_ended_at"], contract["tier"],
                episode["planned_track_count"])
        db.episodes.touch(episode)
    return object_response(serialize(rec))


@bp.post("/sessions/<rid>/cancel")
def cancel_session(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"ProducerEng"})
    rec = get_or_404(db.sessions, rid)
    assert_session_engineer(auth, rec)
    if rec["status"] != "BOOKED":
        raise errors.err(errors.ERR_INVALID_STATE, "Session is not BOOKED")
    rec["status"] = "CANCELLED"
    db.sessions.touch(rec)
    return object_response(serialize(rec))
