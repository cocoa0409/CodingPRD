"""Test-driving logical clock endpoint."""

from flask import Blueprint

import clock
from middleware import require_roles
from services.core import expiry_sweep
from util import fmt_dt, parse_body, parse_dt, success_envelope

bp = Blueprint("clock_routes", __name__)


@bp.route("/damage-recovery/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("RecoveryManager")
    body = parse_body(required_fields=["to_iso8601"])
    target = parse_dt(body["to_iso8601"], "to_iso8601")
    clock.set_current_utc(target)
    expiry_sweep()
    return success_envelope({"current_utc": fmt_dt(clock.get_current_utc())}, "object", 200)
