"""The logical clock (PRD 2.4)."""
from flask import Blueprint

import constants as C
import middleware
import response
import util

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    middleware.require_roles([C.ROLE_BOARD_ADMIN])
    body = middleware.body_json()
    instant = middleware.req_instant(body, "to_iso8601")
    util.set_clock(instant)
    return response.success({}, 200)
