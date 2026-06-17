"""Test-driving clock endpoint (PRD §3.12)."""
from flask import Blueprint

import clock
from auth import require_role
from common import get_json_or_400, require_iso_datetime
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set", methods=["POST"])
def clock_set():
    require_role("ShopManager")
    body = get_json_or_400()
    dt = require_iso_datetime(body, "to_iso8601")
    clock.set_clock(dt)
    return success_object({}, 200)
