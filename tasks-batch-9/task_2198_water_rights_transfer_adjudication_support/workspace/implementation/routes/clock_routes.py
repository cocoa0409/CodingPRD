"""POST /_clock/set_current_utc -- the service's only time source."""
from flask import Blueprint

import clock
import middleware
import response
import validate

bp = Blueprint("clock_routes", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    middleware.authenticate(middleware.ALL_ROLES)
    body = validate.get_body()
    _, parsed = validate.req_instant(body, "current_utc")
    clock.set_now(parsed)
    return response.object_response({"current_utc": clock.now_iso()})
