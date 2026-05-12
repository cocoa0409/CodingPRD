"""/_clock and /_clock/advance test-driving endpoints."""
from flask import Blueprint, request

from clock import current_clock, iso
from middleware import auth_required
from response import success
from services.clock_sweep import advance_clock
from validators import as_iso, require_field


bp = Blueprint("clock", __name__)


@bp.get("/_clock")
@auth_required(["Volunteer", "Organizer", "SkillAdmin"])
def read_clock():
    return success({"now": iso(current_clock())})


@bp.post("/_clock/advance")
@auth_required(["SkillAdmin"])
def advance():
    body = request.get_json(silent=True) or {}
    target = as_iso(require_field(body, "target_time"), "target_time")
    advance_clock(target)
    return success({"now": iso(current_clock())})
