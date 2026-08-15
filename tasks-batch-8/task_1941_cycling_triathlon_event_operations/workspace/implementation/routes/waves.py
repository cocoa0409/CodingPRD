"""Wave endpoints."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_VALIDATION, ERR_INVALID_STATE, not_found
from middleware import require_roles
from response import success_object, success_list, paginate
from services.core import refresh_wave, promote_waitlist
from util import stamp_common, touch, require_fields, require_int, require_bool, require_enum, parse_dt

bp = Blueprint("waves", __name__)

ALL = ("RaceDirector", "PermitCoordinator", "Referee", "Timer", "VolunteerCoordinator", "Athlete")


def get_event_or_404(event_id):
    ev = db.events.get(event_id)
    if not ev:
        raise not_found("event not found")
    return ev


def get_wave_or_404(wave_id):
    w = db.waves.get(wave_id)
    if not w:
        raise not_found("wave not found")
    return w


@bp.post("/events/<event_id>/waves")
def create_wave(event_id):
    require_roles("RaceDirector")
    get_event_or_404(event_id)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["label", "division", "scheduled_start_time", "capacity",
                          "draft_legal", "age_band_min", "age_band_max"])
    if not isinstance(body["label"], str) or not body["label"]:
        raise ApiError(ERR_VALIDATION, "label must be a non-empty string", 400)
    division = require_enum(body["division"], ("AGE_GROUP", "ELITE"), "division")
    parse_dt(body["scheduled_start_time"])
    capacity = require_int(body["capacity"], "capacity")
    draft_legal = require_bool(body["draft_legal"], "draft_legal")
    age_min = require_int(body["age_band_min"], "age_band_min")
    age_max = require_int(body["age_band_max"], "age_band_max")
    if age_max < age_min:
        raise ApiError(ERR_VALIDATION, "age_band_max must be >= age_band_min", 400)

    wave = stamp_common({
        "event_id": event_id,
        "label": body["label"],
        "division": division,
        "scheduled_start_time": body["scheduled_start_time"],
        "actual_start_time": None,
        "capacity": capacity,
        "assigned_count": 0,
        "draft_legal": draft_legal,
        "age_band_min": age_min,
        "age_band_max": age_max,
        "status": "OPEN",
    })
    db.waves[wave["id"]] = wave
    return success_object(wave, status=201)


@bp.get("/events/<event_id>/waves")
def list_waves(event_id):
    require_roles(*ALL)
    get_event_or_404(event_id)
    items = [w for w in db.waves.values() if w["event_id"] == event_id]
    page, limit, offset, total = paginate(items, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/waves/<wave_id>")
def get_wave(wave_id):
    require_roles(*ALL)
    w = get_wave_or_404(wave_id)
    refresh_wave(w)
    return success_object(w)


@bp.post("/waves/<wave_id>/close")
def close_wave(wave_id):
    require_roles("RaceDirector")
    w = get_wave_or_404(wave_id)
    if w["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, f"cannot close from {w['status']}", 409)
    w["status"] = "CLOSED"
    touch(w)
    return success_object(w)


@bp.post("/waves/<wave_id>/reopen")
def reopen_wave(wave_id):
    require_roles("RaceDirector")
    w = get_wave_or_404(wave_id)
    if w["status"] != "CLOSED":
        raise ApiError(ERR_INVALID_STATE, f"cannot reopen from {w['status']}", 409)
    refresh_wave(w)
    if w["assigned_count"] >= w["capacity"]:
        raise ApiError(ERR_INVALID_STATE, "assigned_count at capacity", 409)
    w["status"] = "OPEN"
    touch(w)
    ev = db.events[w["event_id"]]
    promote_waitlist(ev, w)
    return success_object(w)


@bp.get("/waves/<wave_id>/registrations")
def wave_registrations(wave_id):
    require_roles(*ALL)
    w = get_wave_or_404(wave_id)
    items = [r for r in db.registrations.values() if r.get("wave_id") == w["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list(page, limit, offset, total)
