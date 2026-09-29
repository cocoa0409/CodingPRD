"""The logical clock (PRD §2.5). Never wall-clock time."""

from flask import Blueprint

from middleware import authorize, body, req_datetime
from response import raw_object_response
from services import cascade
from util import fmt_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@authorize("ForecastDirector", "ReserveTreasurer")
def set_current_utc():
    data = body()
    moment = req_datetime(data, "current_utc")
    lapsed = cascade.advance_clock(fmt_dt(moment))
    return raw_object_response(
        {"current_utc": data["current_utc"], "lapsed_request_count": lapsed}
    )
