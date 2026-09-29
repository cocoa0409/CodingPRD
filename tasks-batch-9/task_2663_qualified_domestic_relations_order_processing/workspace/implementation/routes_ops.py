"""Test-driving capabilities: the logical clock and the segregation sweep."""
from flask import Blueprint

import services
import validation as v
from auth import endpoint
from envelope import object_response
from store import db

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint("PlanAdministrator")
def set_clock(caller):
    data = v.body()
    moment = v.req_instant(data, "current_utc")
    raw = data["current_utc"].strip()
    previous = db.set_clock(raw, moment)
    return object_response({"current_utc": raw, "previous_utc": previous})


@bp.route("/_ops/run-segregation-sweep", methods=["POST"])
@endpoint("PlanAdministrator")
def run_sweep(caller):
    return object_response(services.run_segregation_sweep())
