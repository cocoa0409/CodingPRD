"""The logical assessment clock (PRD 2.5)."""

from flask import Blueprint

from db import now, set_clock
from middleware import STATE_OFFICER, endpoint, json_body
from response import object_response
from timeutil import fmt_iso
from validators import datetime_field

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(STATE_OFFICER)
def set_current_utc(actor):
    body = json_body()
    moment = datetime_field(body, "to_iso8601")
    set_clock(moment)
    return object_response({"current_utc": fmt_iso(now())})
