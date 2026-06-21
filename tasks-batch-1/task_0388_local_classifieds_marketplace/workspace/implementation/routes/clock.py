"""Test-driving logical clock (PRD §3.9 / §2.10)."""
from flask import Blueprint

import constants as C
from db import store
from domain import run_sweeps
from middleware import auth_context, require_role, get_json_body
from response import object_response
from timeutil import parse_iso
import validate as V

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set", methods=["POST"])
def set_clock():
    user_id, role = auth_context()
    require_role(role, {C.ROLE_PLATFORM_ADMIN})
    body = get_json_body()
    to_iso = V.require_field(body, "to_iso8601")
    store.current_clock = parse_iso(to_iso)
    # Set runs NO sweeps (§3.9). Returns empty data object (output: null).
    return object_response({})


@bp.route("/_clock/advance", methods=["POST"])
def advance_clock():
    user_id, role = auth_context()
    require_role(role, {C.ROLE_PLATFORM_ADMIN})
    body = get_json_body()
    to_iso = V.require_field(body, "to_iso8601")
    store.current_clock = parse_iso(to_iso)
    # Advance moves the clock then runs expiry sweeps (§3.9).
    run_sweeps()
    return object_response({})
