"""Logical-clock control (PRD §2.4, §3.12; SCAFFOLD §1.5).

POST /_clock/set_current_utc  (StudioManager only)
  body: { "to_iso8601": "<ISO 8601 UTC instant>" }
  Sets the logical clock and runs the three time-based sweeps (firing
  completion, booking expiry, series start). Startup default is
  2026-04-01T00:00:00Z and the clock never falls back to wall-clock time.
"""

from flask import Blueprint, request

from clock import clock
from errors import invalid_request
from middleware import get_caller, require_roles
from response import success
from services.transitions import run_sweeps
from services.validation import require_body, require_str

bp = Blueprint("clock_routes", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    caller = get_caller()
    require_roles(caller, {"StudioManager"})
    payload = require_body(request.get_json(silent=True))
    to_iso8601 = require_str(payload, "to_iso8601")
    try:
        clock.set_from_iso(to_iso8601)
    except ValueError:
        raise invalid_request("to_iso8601 must be a valid ISO 8601 instant")
    # Advancing the clock drives the three sweeps (PRD §3.12).
    run_sweeps()
    return success({})
