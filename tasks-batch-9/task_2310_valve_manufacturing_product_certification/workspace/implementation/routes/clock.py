"""The logical works clock (PRD 2.5)."""

from flask import Blueprint

from auth import ANY, require_roles
from db import clock_iso, db
from response import object_response
from validation import get_body, get_datetime

bp = Blueprint("clock", __name__)


@bp.post("/valve-mfg/_clock/set_current_utc")
def set_current_utc():
    require_roles(ANY)
    body = get_body()
    _raw, moment = get_datetime(body, "to_iso8601")
    db.clock = moment
    return object_response({"current_utc": clock_iso()})
