"""The logical compliance clock control (PRD 2.5)."""

from flask import Blueprint

import clock
import response
from middleware import require
from validators import F, parse

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require("PlatformAdmin")
    body = parse("Clock", {"to_iso8601": F("datetime")})
    clock.set_now(body["to_iso8601"])
    return response.ok({"current_utc": clock.now_iso()})
