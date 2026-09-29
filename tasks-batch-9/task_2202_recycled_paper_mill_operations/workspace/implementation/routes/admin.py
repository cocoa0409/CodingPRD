from flask import Blueprint

import auth
import clock
import response
import shape

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.require_roles("MillPlanner", "EnvironmentalOfficer", "EnergyManager")
    data = shape.body()
    shape.reject_unexpected_version(data)
    target = shape.get_dt(data, "to_iso8601", required=True)
    clock.set_now(target)
    return response.ok({"current_utc": clock.now_iso()})
