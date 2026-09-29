"""The logical clock test-driving capability (PRD 2.4)."""

from flask import Blueprint

import db
import response
import validate
from middleware import SYSTEM_ADMIN, require

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require(SYSTEM_ADMIN)
    data = validate.body()
    current_utc = validate.req_instant(data, "current_utc")
    db.set_clock(current_utc)
    return response.object_response({"current_utc": db.clock_str()})
