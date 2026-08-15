"""Logical clock administration (PRD §2.4)."""
import clock
from auth import require_roles
from flask import Blueprint
from response import respond
from util import body, render_dt, req_field, parse_datetime

bp = Blueprint("admin", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("LabDirector")
def set_clock():
    b = body()
    dt = parse_datetime(req_field(b, "to_iso8601"), "to_iso8601")
    clock.set_current(dt)
    return respond({"current_utc": render_dt(clock.now())}, 200)
