"""Test-driving clock endpoint (PRD §3.11)."""

from flask import Blueprint

from db import store, parse_dt, iso
import errors
from errors import err
from middleware import authenticate, require_roles, get_json
from response import ok

bp = Blueprint("clock", __name__)


@bp.route("/marketplace/_clock/set", methods=["POST"])
def set_clock():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin"})
    body = get_json()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise err(errors.ERR_VALIDATION, "Missing required field: to_iso8601")
    dt = parse_dt(body["to_iso8601"])
    if dt is None:
        raise err(errors.ERR_VALIDATION, "to_iso8601 must be an ISO 8601 datetime")
    store.set_clock(dt)
    return ok({"now": iso(dt)}, status=200)
