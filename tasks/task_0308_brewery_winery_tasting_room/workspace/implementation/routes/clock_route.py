"""Test-driving clock route (PRD §3.12). Sets the deterministic server 'now'."""
from flask import Blueprint

import clock
from middleware import authenticate, authorize
from response import success
from validate import get_json_body, require_str
from util import parse_datetime

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    authorize(role, ["ComplianceOfficer"])
    body = get_json_body()
    to_iso8601 = require_str(body, "to_iso8601")
    dt = parse_datetime(to_iso8601, "to_iso8601")
    clock.set_now(dt)
    # output: null per endpoint table -> empty data object envelope
    return success({}, status=200)
