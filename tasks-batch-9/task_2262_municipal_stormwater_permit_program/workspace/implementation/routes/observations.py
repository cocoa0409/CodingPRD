"""Adjudication of pending wet-weather samples."""

from flask import Blueprint

import enums
import middleware as mw
from db import CLOCK, touch
from errors import ApiError
from middleware import body, get_enum, require
from routes.common import find, one, settle
from services import derive

bp = Blueprint("observations", __name__)


@bp.post("/observations/<observation_id>/validate")
def validate_observation(observation_id):
    user_id, _role = require([mw.OPS, mw.MANAGER])
    payload = body()
    decision = get_enum(payload, "decision", enums.VALIDATE_DECISION)

    observation = find("observations", observation_id)
    if (
        observation["observation_type"] != "WET_WEATHER_SAMPLE"
        or observation.get("validation_status") != "PENDING"
    ):
        raise ApiError("ERR_OBSERVATION_NOT_PENDING")
    if observation.get("recorded_by_user_id") == user_id:
        raise ApiError("ERR_SELF_VALIDATION_FORBIDDEN")

    observation["validation_status"] = "VALIDATED" if decision == "VALIDATE" else "REJECTED"
    observation["validated_at"] = CLOCK.stamp()
    touch(observation)
    settle(derive.term_of_observation(observation))
    return one(observation)
