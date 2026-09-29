"""The logical clock capability (PRD 2.5)."""
from flask import Blueprint

import clock
from middleware import ALL_ROLES, body, endpoint
from response import object_response
from util import as_dt, fmt_dt, get_required

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(ALL_ROLES)
def set_current_utc(user_id, role):
    payload = body()
    instant = as_dt(get_required(payload, "current_utc"), "current_utc")
    clock.set_now(instant)
    return object_response({"current_utc": fmt_dt(clock.now())})
