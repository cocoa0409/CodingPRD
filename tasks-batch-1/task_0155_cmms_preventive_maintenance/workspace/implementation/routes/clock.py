"""Test-driving clock (PRD §2.9, §4).

A MaintenanceManager sets the server's current UTC instant; every subsequent
domain reference to "now" uses it. Returns 200 with an empty data object.
"""
from flask import Blueprint

import db
from middleware import authenticate, authorize, get_json_body
from helpers import require_dt
from response import object_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    authorize(role, ["MaintenanceManager"])
    body = get_json_body()
    to = require_dt(body, "to_iso8601")
    with db.LOCK:
        db.set_clock(to)
        # Operation returns 200 with no resource body (PRD §4).
        return object_response({}, 200)
