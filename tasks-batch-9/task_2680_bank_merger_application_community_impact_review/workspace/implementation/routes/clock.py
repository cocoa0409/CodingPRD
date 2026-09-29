"""The logical UTC clock (PRD 2.4)."""
from flask import Blueprint

from db import set_clock
from middleware import ROLE_ANALYST, get_body, req_dt, require_roles
from response import object_response

clock_bp = Blueprint("clock", __name__)


@clock_bp.post("/_clock/set_current_utc")
@require_roles(ROLE_ANALYST)
def set_current_utc():
    body = get_body(required=True)
    instant = req_dt(body, "now")
    set_clock(instant)
    return object_response({"now": body["now"]})
