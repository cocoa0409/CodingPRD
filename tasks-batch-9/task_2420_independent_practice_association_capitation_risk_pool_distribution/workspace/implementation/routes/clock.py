"""The logical clock (PRD 2.5)."""

from flask import Blueprint

import db
import middleware
import response
import validate

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    middleware.require(*middleware.ROLES)
    body = validate.body()
    current_utc = validate.req_instant(body, "current_utc")
    db.set_clock(current_utc)
    return response.ok({"current_utc": current_utc.render()})
