"""Logical clock endpoint (PRD 2.5)."""
from flask import Blueprint, request

import domain
from errors import err_invalid_request
from middleware import require_roles
from response import success
from util import clock_now, set_clock, ts_clock, parse_dt

bp = Blueprint("clock", __name__, url_prefix="/api")


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    to = parse_dt(body.get("to_iso8601"), "to_iso8601")
    if not to > clock_now():
        raise err_invalid_request(
            "to_iso8601 must be strictly later than the current clock reading")
    set_clock(to)
    domain.run_sweep()
    return success({"current_utc": ts_clock(to)}, code=200)
