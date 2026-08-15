"""Logical clock test-driving endpoint (PRD section 2.4)."""

import db
import services
from middleware import authenticate
from response import success_obj
from routes import make_blueprint
from util import body_json, check_shape, parse_dt

bp = make_blueprint("clock")


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_shape(body, {"to_iso8601": {"type": "datetime", "required": True}})
    db.set_clock(parse_dt(body["to_iso8601"], "to_iso8601"))
    # After every set, the stale-check sweep runs over all issued
    # lump-sum-check payouts.
    services.stale_check_sweep()
    return success_obj({"current_utc": body["to_iso8601"]}, 200)
