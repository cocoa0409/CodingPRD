"""Logical clock control (PRD §3.9). Any of the three roles may set the clock."""
from flask import Blueprint

from clock import clock, iso_z
from middleware import require_roles
from response import object_response
from validate import get_json_body, require
from timeutil import parse_iso

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("InventoryManager", "PurchasingAgent", "BarManager")
def set_current_utc():
    body = get_json_body()
    to_iso8601 = require(body, "to_iso8601")
    dt = parse_iso(to_iso8601, "to_iso8601")
    clock.set(dt)
    return object_response({"current_utc": iso_z(dt)})
