"""The logical program clock (PRD sec 2.4)."""

from flask import Blueprint

import db
import middleware as mw
import response

bp = Blueprint("clock", __name__)


@bp.post("/sfsp/_clock/set_current_utc")
@mw.endpoint([mw.ROLE_STATE_AGENCY_REVIEWER])
def set_current_utc():
    body = mw.json_body()
    moment = mw.field_datetime(body, "to_iso8601")
    db.clock.set(moment)
    return response.object_response({"current_utc": db.clock.now_iso()})
