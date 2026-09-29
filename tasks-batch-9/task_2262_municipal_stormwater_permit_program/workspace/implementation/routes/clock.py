"""The logical clock. Tests drive time forward through this endpoint only."""

from flask import Blueprint

import middleware as mw
from db import CLOCK
from middleware import body, get_datetime, require
from response import object_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require(mw.OPERATIONAL_ROLES)
    payload = body()
    moment, _raw = get_datetime(payload, "to_iso8601")
    CLOCK.set(moment)
    return object_response({"current_utc": CLOCK.stamp()})
