"""Test-driving clock control (PRD §3.2)."""
from flask import Blueprint

import clock
import domain
from middleware import require
from response import object_response
import validate as V

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require("Coordinator")
def set_clock():
    body = V.get_body()
    instant = V.require_datetime(body, "to_iso8601")
    clock.set_now(instant)
    # Fire due-date / expiry sweeps (PRD §3.2).
    domain.sweep_expiry_and_overdue()
    return object_response({}, 200)
