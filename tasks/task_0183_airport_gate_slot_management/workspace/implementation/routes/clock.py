"""Test-driving simulated clock (ClockState singleton)."""
from flask import Blueprint

import db
import errors
import helpers
from middleware import authenticate, require_roles
from response import success

bp = Blueprint("clock", __name__)


def _clock_view():
    return {"current_utc": db.clock.get("current_utc")}


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_roles(role, {"OpsAdmin"})
    body = helpers.get_body()
    helpers.require_fields(body, ["to_iso8601"])
    dt, raw = helpers.parse_dt(body["to_iso8601"], "to_iso8601")
    db.clock["current_utc"] = raw
    db.clock["_epoch"] = dt.timestamp()
    return success(_clock_view(), status=200)


@bp.route("/_clock", methods=["GET"])
def get_clock():
    _, role = authenticate()
    require_roles(role, {"OpsAdmin", "SlotCoordinator"})
    return success(_clock_view(), status=200)
