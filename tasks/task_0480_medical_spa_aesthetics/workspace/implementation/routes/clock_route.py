"""Logical clock control endpoint (PRD §2.4)."""
from flask import Blueprint

from middleware import require_roles
from helpers import get_json_body, require_datetime
from response import success_object
from clock import clock

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("ClinicAdmin")
def set_clock():
    body = get_json_body()
    dt = require_datetime(body, "to_iso8601")
    clock.set(dt)
    return success_object({})
