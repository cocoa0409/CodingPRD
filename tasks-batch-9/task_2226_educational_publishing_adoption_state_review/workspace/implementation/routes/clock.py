"""The logical UTC adoption clock (PRD 2.5)."""

import validation as V
from db import iso, now, set_clock
from middleware import authorize
from response import respond

from flask import Blueprint

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(("PlatformAdmin",))
    payload = V.body()
    instant = V.get_datetime(payload, "to_iso8601")
    set_clock(instant)
    return respond({"current_utc": iso(now())})
