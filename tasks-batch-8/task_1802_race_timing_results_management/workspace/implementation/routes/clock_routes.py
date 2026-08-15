from flask import Blueprint

import clock
from middleware import endpoint, STAFF_ROLES
from response import ok
from util import fmt_dt
from validators import get_body, v_dt

bp = Blueprint("clock", __name__)


@bp.post("/race-timing/_clock/set_current_utc")
@endpoint(*STAFF_ROLES)
def set_current_utc():
    body = get_body(("to_iso8601",))
    dt = v_dt(body, "to_iso8601")
    clock.set_now(dt)
    return ok({"current_utc": fmt_dt(clock.now())})
