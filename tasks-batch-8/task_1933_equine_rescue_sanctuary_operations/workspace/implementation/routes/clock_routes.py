from flask import Blueprint

import clock
from auth import authenticate, ROLE_SANCTUARY_DIRECTOR
from response import ok_object
from util import body, iso_z, parse_dt, require_present

bp = Blueprint("clock", __name__)


@bp.post("/rescue-ops/_clock/set_current_utc")
def set_clock():
    authenticate([ROLE_SANCTUARY_DIRECTOR])
    data = body()
    raw = require_present(data, "to_iso8601")
    clock.set_current(parse_dt(raw, "to_iso8601"))
    return ok_object({"current_utc": iso_z(clock.now())})
