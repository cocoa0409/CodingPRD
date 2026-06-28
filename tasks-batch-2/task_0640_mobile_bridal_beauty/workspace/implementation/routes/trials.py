"""Trial session routes (PRD §3.5)."""
from flask import Blueprint, request

import errors
from db import store, LOCK, parse_iso
from middleware import get_identity, require_role, parse_pagination, get_json_body
from response import object_response, array_response
from services.common import base_fields, touch, paginate
from services.validate import require_str, require_datetime, require_int_min

bp = Blueprint("trials", __name__)

NON_TERMINAL_TRIAL = {"BOOKED"}  # only BOOKED is non-terminal


def serialize_trial(t):
    return {
        "id": t["id"],
        "event_id": t["event_id"],
        "artist_id": t["artist_id"],
        "start_utc": t["start_utc"],
        "end_utc": t["end_utc"],
        "status": t["status"],
        "trial_fee_cents": t["trial_fee_cents"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


@bp.route("/bridal-beauty/trials", methods=["POST"])
def create_trial():
    user_id, role = get_identity()
    require_role(role, {"Coordinator", "Client"})
    body = get_json_body()

    with LOCK:
        # Existence left-to-right: event_id then artist_id (PRD §2.5).
        event_id = require_str(body, "event_id")
        artist_id = require_str(body, "artist_id")
        start_dt = require_datetime(body, "start_utc")
        end_dt = require_datetime(body, "end_utc")
        trial_fee = require_int_min(body, "trial_fee_cents", 0)

        if store.events.get(event_id) is None:
            raise errors.not_found()
        if store.artists.get(artist_id) is None:
            raise errors.not_found()

        # end_utc must be strictly after start_utc.
        if not (end_dt > start_dt):
            raise errors.invalid_request("end_utc must be after start_utc")

        # Window conflict against non-terminal trials of the same artist (closed-open).
        for t in store.trials.values():
            if t["artist_id"] != artist_id or t["status"] not in NON_TERMINAL_TRIAL:
                continue
            ts = t["_start_dt"]
            te = t["_end_dt"]
            # [start, end) overlap [ts, te): overlap iff start < te and ts < end.
            if start_dt < te and ts < end_dt:
                raise errors.trial_window_conflict()

        rec = base_fields()
        rec.update({
            "event_id": event_id,
            "artist_id": artist_id,
            "start_utc": body["start_utc"],
            "end_utc": body["end_utc"],
            "_start_dt": start_dt,
            "_end_dt": end_dt,
            "status": "BOOKED",
            "trial_fee_cents": trial_fee,
        })
        store.trials[rec["id"]] = rec
        return object_response(serialize_trial(rec), 201)


@bp.route("/bridal-beauty/trials/<trial_id>", methods=["GET"])
def get_trial(trial_id):
    user_id, role = get_identity()
    require_role(role, {"Coordinator", "Client", "Artist"})
    t = store.trials.get(trial_id)
    if t is None:
        raise errors.not_found()
    return object_response(serialize_trial(t), 200)


@bp.route("/bridal-beauty/trials", methods=["GET"])
def list_trials():
    user_id, role = get_identity()
    require_role(role, {"Coordinator", "Client", "Artist"})
    limit, offset = parse_pagination()
    event_f = request.args.get("event_id")
    artist_f = request.args.get("artist_id")
    status_f = request.args.get("status")
    items = list(store.trials.values())
    if event_f is not None:
        items = [t for t in items if t["event_id"] == event_f]
    if artist_f is not None:
        items = [t for t in items if t["artist_id"] == artist_f]
    if status_f is not None:
        items = [t for t in items if t["status"] == status_f]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_trial(t) for t in page], limit, offset, total)


@bp.route("/bridal-beauty/trials/<trial_id>/complete", methods=["POST"])
def complete_trial(trial_id):
    user_id, role = get_identity()
    require_role(role, {"Artist"})
    with LOCK:
        t = store.trials.get(trial_id)
        if t is None:
            raise errors.not_found()
        # Ownership: acting Artist.id == trial.artist_id (PRD §2.1, §3.5).
        if user_id != t["artist_id"]:
            raise errors.forbidden_role("Acting artist is not the trial's artist")
        if t["status"] != "BOOKED":
            raise errors.invalid_state("Trial is not BOOKED")
        if not (store.clock_now >= t["_start_dt"]):
            raise errors.invalid_state("Current time has not reached the trial start")
        t["status"] = "COMPLETED"
        touch(t)
        return object_response(serialize_trial(t), 200)


@bp.route("/bridal-beauty/trials/<trial_id>/no-show", methods=["POST"])
def no_show_trial(trial_id):
    user_id, role = get_identity()
    require_role(role, {"Coordinator"})
    with LOCK:
        t = store.trials.get(trial_id)
        if t is None:
            raise errors.not_found()
        if t["status"] != "BOOKED":
            raise errors.invalid_state("Trial is not BOOKED")
        if not (store.clock_now >= t["_end_dt"]):
            raise errors.invalid_state("Current time has not reached the trial end")
        t["status"] = "NO_SHOW"
        touch(t)
        return object_response(serialize_trial(t), 200)


@bp.route("/bridal-beauty/trials/<trial_id>/cancel", methods=["POST"])
def cancel_trial(trial_id):
    user_id, role = get_identity()
    require_role(role, {"Client"})
    with LOCK:
        t = store.trials.get(trial_id)
        if t is None:
            raise errors.not_found()
        # Ownership via the event's client_id (PRD §2.4).
        e = store.events.get(t["event_id"])
        if e is None or user_id != e["client_id"]:
            raise errors.not_event_owner()
        if t["status"] != "BOOKED":
            raise errors.invalid_state("Trial is not BOOKED")
        t["status"] = "CANCELLED"
        touch(t)
        return object_response(serialize_trial(t), 200)
