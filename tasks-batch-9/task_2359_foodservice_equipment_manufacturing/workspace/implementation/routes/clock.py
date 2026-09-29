"""The logical clock (PRD Section 2.5)."""
from flask import Blueprint

import validate
from db import db
from middleware import authorize
from response import ok
from services import derive

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize("PlatformAdmin")
    payload = validate.body()
    to_iso8601 = validate.datetime_field(payload, "to_iso8601")
    db.clock = to_iso8601
    derive.reconcile_after_clock_move()
    return ok({})
