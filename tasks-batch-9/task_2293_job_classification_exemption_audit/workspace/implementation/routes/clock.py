"""Logical clock capability (PRD 2.5)."""
from flask import Blueprint

import db
from middleware import body, endpoint
from response import success
from validation import req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(["ProgramAdmin"])
def set_current_utc():
    payload = body()
    moment = req_datetime(payload, "current_utc")
    db.set_clock(moment)
    return success({}, 200)
