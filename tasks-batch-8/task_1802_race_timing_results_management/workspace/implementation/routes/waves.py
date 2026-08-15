from flask import Blueprint

import clock
import db
from db import new_entity, touch
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_WAVE_INDEX_TAKEN,
    ERR_WAVE_SPACING_VIOLATION,
)
from middleware import endpoint
from response import ok
from serializers import ser_wave
from validators import get_body, get_or_404, v_dt, v_int

bp = Blueprint("waves", __name__)

# Gap required between the scheduled starts of any two waves of one race.
# (PRD section 3.1 names this constant WAVE_GAP_MINUTES without fixing a value.)
WAVE_GAP_MINUTES = 5


@bp.post("/race-timing/waves")
@endpoint("RaceDirector")
def create_wave():
    body = get_body(("race_id", "wave_index", "scheduled_start_time", "max_capacity"))
    race = get_or_404(db.races, body.get("race_id"))
    wave_index = v_int(body, "wave_index")
    if wave_index < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "wave_index must be at least 1")
    scheduled = v_dt(body, "scheduled_start_time")
    max_capacity = v_int(body, "max_capacity")
    if max_capacity <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "max_capacity must be greater than zero")

    siblings = [w for w in db.waves.values() if w["race_id"] == race["id"]]
    # spacing rule evaluated first; absolute difference, equality allowed
    gap_sec = WAVE_GAP_MINUTES * 60
    for w in siblings:
        diff = abs((scheduled - w["scheduled_start_time"]).total_seconds())
        if diff < gap_sec:
            raise ApiError(
                ERR_WAVE_SPACING_VIOLATION,
                409,
                "scheduled_start_time is within WAVE_GAP_MINUTES of another wave",
            )
    # then wave_index uniqueness
    if any(w["wave_index"] == wave_index for w in siblings):
        raise ApiError(
            ERR_WAVE_INDEX_TAKEN, 409, "wave_index is already used in this race"
        )

    wave = new_entity()
    wave.update(
        {
            "race_id": race["id"],
            "wave_index": wave_index,
            "scheduled_start_time": scheduled,
            "max_capacity": max_capacity,
            "actual_start_time": None,
            "status": "SCHEDULED",
        }
    )
    db.waves[wave["id"]] = wave
    return ok(ser_wave(wave), 201)


@bp.post("/race-timing/waves/<wave_id>/start")
@endpoint("TimingOperator")
def start_wave(wave_id):
    wave = get_or_404(db.waves, wave_id)
    race = db.races.get(wave["race_id"])
    if wave["status"] != "SCHEDULED" or (
        race is not None and race["status"] not in ("TIMING_LOCKED", "IN_PROGRESS")
    ):
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Wave must be SCHEDULED and its race in TIMING_LOCKED or IN_PROGRESS",
        )
    wave["status"] = "STARTED"
    wave["actual_start_time"] = clock.now()
    touch(wave)
    if race is not None and race["status"] == "TIMING_LOCKED":
        race["status"] = "IN_PROGRESS"
        touch(race)
    return ok(ser_wave(wave))
