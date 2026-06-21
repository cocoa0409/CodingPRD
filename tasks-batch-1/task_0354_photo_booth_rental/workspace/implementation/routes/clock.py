"""Test-driving logical clock (PRD §3.10)."""
from flask import Blueprint

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success
import helpers

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = helpers.get_json()
    dt = helpers.parse_datetime(body, "to_iso8601")
    db.set_clock(dt)
    return success(None, 200)


@bp.route("/_clock", methods=["GET"])
def read_clock():
    # PRD §2.1: anonymous-readable; no auth headers required.
    now = db.get_clock()
    iso = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return success({"now": iso}, 200)
