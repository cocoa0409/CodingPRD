from flask import Blueprint

import db
from calc import iso
from middleware import authenticate, require_role, locked
from response import ok
from validators import body, req_field, as_dt

bp = Blueprint("clock", __name__)


@bp.post("/pole-program/_clock/set_current_utc")
@locked
def set_current_utc():
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    d = body()
    target = as_dt(req_field(d, "to_iso8601"), "to_iso8601")
    db.set_clock(target)
    return ok({"now_iso8601": iso(db.clock_now())}, 200)
