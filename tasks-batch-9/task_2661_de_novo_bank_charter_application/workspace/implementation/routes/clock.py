"""Logical clock control (PRD 89).  Moves forward only and mutates no row."""
from flask import Blueprint

import db
import response
import util
import validation as v
from errors import err
from middleware import authenticate

bp = Blueprint("clock", __name__)


@bp.post("/de-novo/_clock/set_current_utc")
def set_current_utc():
    authenticate(("PlatformAdmin",))
    data = v.body()
    target = v.req_dt(data, "to_iso8601")
    if target < db.clock():
        raise err("ERR_CLOCK_NOT_MONOTONIC")
    db.set_clock(target)
    return response.object_response({"current_utc": util.iso_clock(target)})
