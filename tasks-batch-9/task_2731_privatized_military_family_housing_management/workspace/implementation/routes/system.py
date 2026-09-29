"""The logical clock setter (PRD 2.4).  This endpoint is unauthenticated."""

from flask import Blueprint

import middleware as mw
import response as resp
from db import set_clock

bp = Blueprint("system", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    body = mw.json_body()
    moment = mw.v_datetime(body, "current_utc", required=True)
    set_clock(moment)
    return resp.empty(200)
