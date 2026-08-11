from flask import Blueprint
from middleware import get_caller, require_role, get_json_body
from services.common import require_datetime
from response import success_object
from db import CLOCK, to_iso
from services.sweeps import run_sweeps

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    body = get_json_body()
    dt = require_datetime(body, "to_iso8601")
    CLOCK.set(dt)
    sweeps = run_sweeps()
    return success_object({"current_utc": to_iso(CLOCK.get()), "sweeps_applied": sweeps})
