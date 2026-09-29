"""The server-owned logical clock (PRD 2.5)."""
from flask import Blueprint

import shape
from auth import LEAGUE_OFFICER, endpoint
from envelope import empty
from store import db

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(LEAGUE_OFFICER)
def set_current_utc(actor):
    body = shape.body()
    moment = shape.req_dt(body, "current_utc")
    # The clock jumps; no entity is mutated and no sweep is performed.
    db.clock = moment
    return empty(200)
