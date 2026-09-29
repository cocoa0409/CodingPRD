"""The test-driving logical clock (PRD 2.5)."""

from flask import Blueprint

import db
import middleware
import response
import validate

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    middleware.require(*middleware.ANY_ROLE)
    body = validate.json_body()
    _raw, instant = validate.datetime_field(body, "current_utc")
    db.set_clock(instant)
    return response.ok({})
