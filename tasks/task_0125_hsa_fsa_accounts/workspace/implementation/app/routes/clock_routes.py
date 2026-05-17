"""Server-clock test-driving endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import require_auth
from ..clock import format_iso
from ..errors import ApiError
from ..helpers import get_json_body, parse_iso_field, require_fields
from ..responses import build_success_envelope
from ..store import store


bp = Blueprint("clock_routes", __name__)


@bp.route("/_clock", methods=["GET"])
@require_auth(["PlanAdministrator", "Auditor"])
def read_clock():
    return jsonify(build_success_envelope({"now": format_iso(store.clock.now())})), 200


@bp.route("/_clock/advance", methods=["POST"])
@require_auth(["PlanAdministrator"])
def advance_clock():
    body = get_json_body(allow_empty=False)
    require_fields(body, ["to"])
    to_dt = parse_iso_field(body["to"], "to")
    try:
        new_now = store.clock.advance_to(to_dt)
    except ValueError:
        raise ApiError("ERR_BAD_REQUEST", "Clock advance must be non-decreasing.")
    return jsonify(build_success_envelope({"now": format_iso(new_now)})), 200
