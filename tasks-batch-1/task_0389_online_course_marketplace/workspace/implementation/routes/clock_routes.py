"""Test-driving logical clock endpoint (PRD §2.8)."""
from flask import Blueprint, request

import clock
import response
from db import iso
from errors import err
from middleware import authenticate, require_roles
from services.common import require_field, parse_dt

bp = Blueprint("clock_routes", __name__)


def _body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    principal = authenticate()
    require_roles(principal, "PlatformAdmin")
    body = _body()
    to_iso = require_field(body, "to_iso8601")
    dt = parse_dt(to_iso)
    clock.set_now(dt)
    return response.success({"current_utc": iso(dt)}, status=200)
