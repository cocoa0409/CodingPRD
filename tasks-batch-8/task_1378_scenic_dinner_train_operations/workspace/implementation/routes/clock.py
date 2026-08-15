"""Logical clock endpoint (PRD section 2.5): OperationsManager-only; advancing
the clock runs the expiry sweep and reports the new value as current_utc."""
from flask import Blueprint

import db
from auth import require_roles
from envelope import success_obj
from services.core import sweep
from timeutil import iso_z
from validators import body, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/railroad/_clock/set_current_utc")
def set_current_utc():
    require_roles("OperationsManager")
    data = body()
    target = req_dt(data, "to_iso8601")
    db.set_clock(target)
    sweep()
    return success_obj({"current_utc": iso_z(db.clock_now())}, 200)
