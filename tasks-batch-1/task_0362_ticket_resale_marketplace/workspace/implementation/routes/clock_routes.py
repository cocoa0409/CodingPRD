from flask import Blueprint

import clock
import validate
import response
import errors
from errors import err
from middleware import get_user_context, require_role
from services import sweeps

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set")
def set_clock():
    body = validate.get_json_body()
    to_iso8601 = validate.require_string(body, "to_iso8601")
    dt = clock.parse_iso(to_iso8601)
    if dt is None:
        raise err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 datetime")
    _, role = get_user_context()
    require_role(role, ("PlatformAdmin",))
    clock.set_now(dt)
    sweeps.run_all()
    return response.object_response({"current_utc": clock.now_iso()}, 200)


@bp.post("/_clock/advance")
def advance_clock():
    body = validate.get_json_body()
    by_minutes = validate.require_int(body, "by_minutes")
    _, role = get_user_context()
    require_role(role, ("PlatformAdmin",))
    clock.set_now(clock.add_minutes(clock.now(), by_minutes))
    sweeps.run_all()
    return response.object_response({"current_utc": clock.now_iso()}, 200)
