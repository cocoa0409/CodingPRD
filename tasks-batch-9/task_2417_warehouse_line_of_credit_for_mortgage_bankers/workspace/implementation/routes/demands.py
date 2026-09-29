"""Escalating a repurchase demand (PRD 3.7)."""

from flask import Blueprint

from clock import clock
from db import db, touch
from errors import ApiError
from middleware import CREDIT_OFFICER, require_auth
from response import ok
from routes.common import get_demand
from serializers import demand_out
from services.states import restrict_if_active
from validation import body

bp = Blueprint("demands", __name__)


@bp.post("/repurchase-demands/<demand_id>/escalate")
def escalate_demand(demand_id):
    require_auth([CREDIT_OFFICER])
    demand = get_demand(demand_id)
    body()
    # priority 17: both halves surface the same code
    if demand["status"] != "OPEN" or clock.now() < demand["deadline_at"]:
        raise ApiError("ERR_REPURCHASE_DEMAND_NOT_OPEN",
                       "Only an OPEN demand whose deadline has passed may be "
                       "escalated.")
    advance = db.advances[demand["advance_id"]]
    facility = db.facilities[advance["facility_id"]]
    demand["status"] = "ESCALATED"
    touch(demand)
    restrict_if_active(facility)
    touch(facility)
    return ok(demand_out(demand))
