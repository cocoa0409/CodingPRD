"""Logical-clock control (PRD 2.4).  The clock never reads wall-clock time."""

from flask import Blueprint

import db
from middleware import authenticate, body
from response import object_response
from services.money import parse_iso_datetime
from validation import Field, validate_body

bp = Blueprint("clock", __name__)

CLOCK_SPEC = {"current_utc": Field("datetime", required=True)}


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(("PlatformAdmin",))
    values = validate_body(body(), CLOCK_SPEC)
    moment = parse_iso_datetime(values["current_utc"])
    previous = db.set_clock(moment)
    return object_response({
        "current_utc": db.iso_ms(moment),
        "previous_utc": db.iso_ms(previous),
    })
