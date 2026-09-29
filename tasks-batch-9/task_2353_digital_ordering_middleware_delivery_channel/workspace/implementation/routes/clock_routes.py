"""POST /_clock/set_current_utc — setting the clock is deliberately inert."""
from flask import Blueprint

import clock
import middleware
import response
import validation

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
@middleware.endpoint(middleware.PLATFORM_ADMIN)
def set_current_utc():
    payload = validation.body()
    instant = validation.req_datetime(payload, "current_utc")
    clock.set_now(instant)
    return response.object_response({"current_utc": clock.fmt(clock.now())}, 200)
