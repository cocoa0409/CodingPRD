"""Logical clock endpoints. PRD §3.12 — PlatformAdmin only."""
from flask import Blueprint

import db
import errors
import response
import middleware as mw
from services import clock as clock_svc
from routes.helpers import get_json_body

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set", methods=["POST"])
def set_clock():
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"PlatformAdmin"})  # priority 2
    body = get_json_body()
    to_iso8601 = body.get("to_iso8601")
    if not isinstance(to_iso8601, str) or to_iso8601 == "":
        raise errors.invalid_request("to_iso8601 is required.")
    try:
        dt = db.parse_iso(to_iso8601)
    except ValueError:
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 timestamp.")
    db.set_clock(dt)
    # Endpoint output is null per §1.5; return an empty object envelope.
    return response.success({}, status=200)


@bp.route("/_clock/advance", methods=["POST"])
def advance_clock():
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"PlatformAdmin"})  # priority 2
    body = get_json_body()
    to_iso8601 = body.get("to_iso8601")
    if not isinstance(to_iso8601, str) or to_iso8601 == "":
        raise errors.invalid_request("to_iso8601 is required.")
    try:
        dt = db.parse_iso(to_iso8601)
    except ValueError:
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 timestamp.")
    db.set_clock(dt)
    # Fire all due timers (auction closes, offer expiries) at the new clock.
    clock_svc.fire_due_timers()
    return response.success({}, status=200)
