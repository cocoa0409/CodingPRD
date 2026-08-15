from flask import Blueprint

import clock
import services
from auth import authenticate, authorize
from errors import ERR_INVALID_REQUEST, raise_err
from util import body_json, parse_iso_datetime, success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = authenticate()
    authorize(role, ["ProgramAdministrator"])
    body = body_json()
    raw = body.get("to_iso8601")
    dt = parse_iso_datetime(raw)
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 UTC timestamp")
    clock.set_current(dt)
    services.apply_time_transitions()
    return success_object({"current_utc": raw.strip()}, 200)
