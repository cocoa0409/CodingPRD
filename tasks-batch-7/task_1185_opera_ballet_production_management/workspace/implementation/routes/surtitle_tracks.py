"""SurtitleTrack routes (PRD 3.7) — includes the CUES_LOCKED -> TRANSLATED
revision loop; the machine has no terminal state."""

from flask import Blueprint

from db import store
from errors import ERR_INVALID_STATE, conflict
from middleware import require_roles
from response import ok_object
from routes.common import get_or_404, list_response
from util import json_body, new_record, req_enum, req_int, req_str, to_public, touch

bp = Blueprint("surtitle_tracks", __name__)

TARGET_STATES = ("TRANSLATED", "CUES_LOCKED", "LIVE")
_ALLOWED = {
    ("DRAFT", "TRANSLATED"),
    ("TRANSLATED", "CUES_LOCKED"),
    ("CUES_LOCKED", "TRANSLATED"),  # revision loop
    ("CUES_LOCKED", "LIVE"),
}


@bp.post("/opera/surtitle-tracks")
def create_track():
    require_roles("TechnicalDirector")
    body = json_body()
    production_id = req_str(body, "production_id")
    language = req_str(body, "language")
    cue_count = req_int(body, "cue_count", min_value=1)
    prod = get_or_404(store.productions, production_id, "Production")
    rec = new_record(
        production_id=prod["id"],
        language=language,
        cue_count=cue_count,
        status="DRAFT",
    )
    store.surtitle_tracks[rec["id"]] = rec
    return ok_object(to_public(rec), 201)


@bp.get("/opera/surtitle-tracks")
def list_tracks():
    require_roles("Any")
    return list_response(
        store.surtitle_tracks.values(),
        [("production_id", "production_id"), ("language", "language"),
         ("status", "status")],
    )


@bp.get("/opera/surtitle-tracks/<tid>")
def get_track(tid):
    require_roles("Any")
    return ok_object(to_public(get_or_404(store.surtitle_tracks, tid,
                                          "SurtitleTrack")))


@bp.post("/opera/surtitle-tracks/<tid>/transition")
def transition_track(tid):
    require_roles("TechnicalDirector")
    body = json_body()
    to_state = req_enum(body, "to_state", TARGET_STATES)
    track = get_or_404(store.surtitle_tracks, tid, "SurtitleTrack")
    if (track["status"], to_state) not in _ALLOWED:
        raise conflict(ERR_INVALID_STATE,
                       f"SurtitleTrack cannot transition "
                       f"{track['status']} -> {to_state}")
    track["status"] = to_state
    touch(track)
    return ok_object(to_public(track))
