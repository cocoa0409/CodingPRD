"""WeatherObservation endpoints."""
from flask import Blueprint
from datetime import timedelta
import db
from middleware import require_roles, get_pagination, get_json_body
from response import success_object, success_created, success_list
from errors import *

bp = Blueprint("observations", __name__)

ALLOWED_FIELDS = {"storm_event_id", "source_name", "observed_at", "accumulation_inches", "note"}


@bp.route("/observations", methods=["POST"])
def create_observation():
    user_id, role = require_roles("PlatformAdmin")
    body = get_json_body()
    unknown = set(body.keys()) - ALLOWED_FIELDS
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown fields: {', '.join(unknown)}", 400)

    storm_event_id = body.get("storm_event_id")
    if not storm_event_id:
        raise ApiError(ERR_INVALID_REQUEST, "storm_event_id is required", 400)
    event = db.storm_events.get(storm_event_id)
    if not event:
        raise ApiError(ERR_NOT_FOUND, f"StormEvent {storm_event_id} not found", 404)

    source_name = body.get("source_name")
    observed_at = body.get("observed_at")
    accumulation = body.get("accumulation_inches")

    if not source_name:
        raise ApiError(ERR_INVALID_REQUEST, "source_name is required", 400)
    if not observed_at:
        raise ApiError(ERR_INVALID_REQUEST, "observed_at is required", 400)
    if accumulation is None or accumulation <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "accumulation_inches must be > 0", 400)

    # Check observed_at inside [window_start, window_end + 6h]
    obs_dt = db._parse_iso(observed_at)
    ws = db._parse_iso(event.get("window_start"))
    we = db._parse_iso(event.get("window_end"))
    if not obs_dt or not ws or not we:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid dates", 400)
    grace_end = we + timedelta(hours=6)
    if not (ws <= obs_dt <= grace_end):
        raise ApiError(ERR_OBSERVATION_OUT_OF_WINDOW, "observed_at outside eligible window", 422)

    obs = {
        "id": db._new_id(),
        "storm_event_id": storm_event_id,
        "source_name": source_name,
        "observed_at": observed_at,
        "accumulation_inches": accumulation,
        "note": body.get("note"),
        "created_at": db.now_iso(),
    }
    db.observations.create(obs)
    return success_created(obs)


@bp.route("/storm-events/<id>/observations", methods=["GET"])
def list_event_observations(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact", "ClaimsAdjuster")
    event = db.storm_events.get(id)
    if not event:
        raise ApiError(ERR_NOT_FOUND, f"StormEvent {id} not found", 404)
    limit, offset = get_pagination()
    all_obs = sorted(
        [o for o in db.observations.list_all() if o.get("storm_event_id") == id],
        key=lambda o: o.get("created_at", ""),
    )
    total = len(all_obs)
    page = all_obs[offset:offset + limit]
    return success_list(page, total, limit, offset)
