"""The program's logical clock (PRD §2.4)."""

from flask import Blueprint

import clock
import response
import validators as V
from middleware import ROLE_PROGRAM_ADMIN, roles

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
@roles(ROLE_PROGRAM_ADMIN)
def set_current_utc():
    payload = V.body()
    _raw, instant = V.get_datetime(payload, "current_utc")
    clock.set_now(instant)
    return response.object_response({"current_utc": clock.iso_now()})
