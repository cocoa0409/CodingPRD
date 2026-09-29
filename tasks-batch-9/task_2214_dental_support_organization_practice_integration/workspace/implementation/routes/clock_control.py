"""The logical-clock driver used by the test harness (PRD 2.3)."""

from flask import Blueprint

import clock
import config
import middleware
import payload
import response
from errors import ApiError

bp = Blueprint("clock_control", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    middleware.authorize(config.ALL_ROLES)
    data = payload.body()
    requested = payload.timestamp(data, "current_utc")
    if requested < clock.now():
        raise ApiError(
            "ERR_CLOCK_NOT_MONOTONIC",
            "The logical clock never moves backwards.",
        )
    # An equal value is accepted as a no-op.
    clock.set_now(requested)
    return response.object_response({}, 200)
