from flask import Blueprint

import db
from auth import require_roles
from errors import ApiError
from response import ok_object
from services import sweep
from validators import get_body, parse_iso8601

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles({"SystemAdmin"})
    body = get_body()
    dt = parse_iso8601(body.get("to_iso8601"))
    if dt is None:
        raise ApiError("ERR_VALIDATION_FAILED", "to_iso8601 must be a valid ISO 8601 instant")
    db.clock.set(dt)
    sweep.epoch_sweep()
    return ok_object({}, 200)
