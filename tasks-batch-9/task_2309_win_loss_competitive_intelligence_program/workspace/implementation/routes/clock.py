"""The logical clock (PRD 2.5)."""
from flask import Blueprint

from db import db
from middleware import ANY_ROLE, endpoint
from response import object_response
from util import fmt_dt
from validate import body, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(ANY_ROLE)
def set_current_utc():
    payload = body()
    current = req_dt(payload, "current_utc")
    db.clock = current
    return object_response({"current_utc": fmt_dt(current)})
