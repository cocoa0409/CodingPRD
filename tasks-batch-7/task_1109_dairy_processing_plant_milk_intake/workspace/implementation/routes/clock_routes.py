"""Test-driving logical clock endpoint (PRD 2.6)."""
from flask import Blueprint

from db import set_clock
from helpers import body, req_dt
from middleware import require_roles
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/dairy/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("PlantController")
    data = body()
    target = req_dt(data, "to_iso8601")
    set_clock(target)
    return success_object({}, 200)
