"""The logical clock test-driving capability (PRD 2.4)."""

from flask import Blueprint

import response as R
import validation as V
from db import iso, now_dt, set_clock
from middleware import auth

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@auth("AssociationSecretary", "AssessmentClerk", "BoardTreasurer", "RoadCommissioner")
def set_current_utc():
    body = V.get_body()
    instant = V.req_dt(body, "to_iso8601")
    set_clock(instant)
    return R.ok({"current_utc": iso(now_dt())})
