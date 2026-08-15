"""POST /_clock/set_current_utc — move the logical clock and run the sweep."""
from flask import Blueprint

import db
from auth import require_roles
from envelope import success_obj
from services.sweep import run_sweep
from timeutil import iso_z
from validators import body, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("AirportManager")
    data = body()
    target = req_dt(data, "to_iso8601")
    db.set_clock(target)
    run_sweep(target)
    return success_obj({"current_utc": iso_z(db.clock_now())}, 200)
