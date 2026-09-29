"""The logical plant clock endpoint (PRD 2.4)."""

from flask import Blueprint

import clock
import response
import validation
from auth import require_auth

bp = Blueprint("clock_control", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_auth("PlantAdmin")
    b = validation.body()
    _raw, parsed = validation.f_datetime(b, "current_utc", required=True)
    clock.set_now(parsed)
    return response.ok({})
