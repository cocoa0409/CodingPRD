"""ResponseClockPause standalone endpoints."""
from flask import Blueprint

import clock
import domain
import response
from auth import require_roles
from errors import ApiError
from routes.common import load_pause

bp = Blueprint("pauses", __name__)


@bp.route("/gas-ops/response-clock-pauses/<pauseId>/end", methods=["POST"])
@require_roles("Dispatcher", "Supervisor")
def end_pause(pauseId, user_id, role):
    pause = load_pause(pauseId)
    if pause["ended_at"] is not None:
        raise ApiError("ERR_INVALID_STATE", "Pause is not OPEN", 409)
    pause["ended_at"] = clock.now()
    domain.bump(pause)
    return response.success(domain.ser_pause(pause), 200)
