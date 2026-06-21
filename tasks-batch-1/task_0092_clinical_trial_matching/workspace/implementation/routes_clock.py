"""Test-driving clock endpoint (PRD §3.8)."""
from flask import Blueprint

import clock
from errors import err
from middleware import require
from response import object_response
from util import parse_dt
from validate import get_json

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require("Sponsor", "CoordinatorStaff", "IRBReviewer", "SafetyOfficer", "Investigator")
def set_clock(caller_id=None, caller_role=None):
    body = get_json()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        err("ERR_INVALID_REQUEST", "Missing required field: to_iso8601")
    dt = parse_dt(body["to_iso8601"])
    if dt is None:
        err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime")
    clock.set_now(dt)
    return object_response({}, 200)
